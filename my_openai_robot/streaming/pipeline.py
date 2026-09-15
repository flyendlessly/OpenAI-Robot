"""Streaming audio pipeline for concurrent LLM generation, TTS synthesis, and audio playback."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Tuple

from ..audio_io import SoundDeviceSpeaker
from ..logger import get_logger
from ..speech_service import SpeechService
from .sentence_splitter import SentenceSplitter

logger = get_logger("streaming.pipeline")


@dataclass
class StreamPipelineResult:
    """流式流水线执行结果汇总"""
    full_text: str
    tts_characters: int = 0
    first_token_latency_ms: float = 0.0  # 首个 Token 延迟
    first_audio_latency_ms: float = 0.0  # 首段音频开播延迟
    total_time_ms: float = 0.0           # 总耗时
    audio_chunks: List[bytes] = field(default_factory=list)


class StreamingAudioPipeline:
    """流式并发音频流水线 (Producer-Consumer Multithreaded Pipeline)

    架构设计：
    ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
    │  LLM Token 流   │ ────> │  TTS 合成队列   │ ────> │  音频播放队列   │
    │ (SentenceSplit) │       │ (Azure Speech)  │       │ (扬声器输出)    │
    └─────────────────┘       └─────────────────┘       └─────────────────┘
    """

    def __init__(
        self,
        speech_service: SpeechService,
        speaker: Optional[SoundDeviceSpeaker] = None,
        *,
        sentence_splitter: Optional[SentenceSplitter] = None,
    ) -> None:
        self.speech_service = speech_service
        self.speaker = speaker
        self.splitter = sentence_splitter or SentenceSplitter()

    def run(
        self,
        token_stream: Iterable[str],
        *,
        on_token_callback: Optional[Callable[[str], None]] = None,
        on_sentence_callback: Optional[Callable[[str], None]] = None,
        synthesize: bool = True,
        play_audio: bool = True,
    ) -> StreamPipelineResult:
        """执行流式流水线：消费 Token 流，分句并发合成 TTS，并连续推送到扬声器播放"""
        start_time = time.perf_counter()
        first_token_time: Optional[float] = None
        first_audio_time: Optional[float] = None

        full_text_parts: List[str] = []
        collected_audio_chunks: List[bytes] = []
        total_tts_chars = 0

        # 如果不需要合成或者不需要播放，进行降级快速处理
        if not synthesize:
            for token in token_stream:
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                full_text_parts.append(token)
                if on_token_callback:
                    on_token_callback(token)

            full_text = "".join(full_text_parts).strip()
            total_time = (time.perf_counter() - start_time) * 1000
            first_token_latency = (
                (first_token_time - start_time) * 1000 if first_token_time else 0.0
            )
            return StreamPipelineResult(
                full_text=full_text,
                tts_characters=0,
                first_token_latency_ms=first_token_latency,
                first_audio_latency_ms=0.0,
                total_time_ms=total_time,
            )

        # 队列定义：哨兵对象 None 表示流结束
        sentence_queue: queue.Queue[Optional[str]] = queue.Queue(maxsize=16)
        audio_queue: queue.Queue[Optional[Tuple[str, bytes]]] = queue.Queue(maxsize=16)

        tts_errors: List[Exception] = []
        play_errors: List[Exception] = []

        # -------------------------------------------------------------
        # 1. 消费者线程 1：TTS 语音合成
        # -------------------------------------------------------------
        def tts_worker() -> None:
            nonlocal total_tts_chars
            while True:
                try:
                    sentence = sentence_queue.get()
                    if sentence is None:
                        # 收到结束哨兵
                        audio_queue.put(None)
                        sentence_queue.task_done()
                        break

                    if sentence.strip():
                        t0 = time.perf_counter()
                        audio_bytes = self.speech_service.synthesize(sentence)
                        elapsed_ms = (time.perf_counter() - t0) * 1000
                        logger.debug("TTS synthesized sentence '%s' (%d bytes, %.1f ms)", sentence, len(audio_bytes), elapsed_ms)
                        total_tts_chars += len(sentence)
                        audio_queue.put((sentence, audio_bytes))

                    sentence_queue.task_done()
                except Exception as exc:
                    logger.error("TTS worker failed on sentence: %s", exc)
                    tts_errors.append(exc)
                    audio_queue.put(None)
                    sentence_queue.task_done()
                    break

        # -------------------------------------------------------------
        # 2. 消费者线程 2：音频播放
        # -------------------------------------------------------------
        def playback_worker() -> None:
            nonlocal first_audio_time
            while True:
                try:
                    item = audio_queue.get()
                    if item is None:
                        audio_queue.task_done()
                        break

                    sentence, audio_bytes = item
                    if audio_bytes:
                        if first_audio_time is None:
                            first_audio_time = time.perf_counter()
                            logger.info(
                                "⚡ Time to First Audio (TTFA): %.1f ms (first chunk: '%s')",
                                (first_audio_time - start_time) * 1000,
                                sentence,
                            )

                        collected_audio_chunks.append(audio_bytes)
                        if play_audio and self.speaker:
                            self.speaker.play(audio_bytes)

                    audio_queue.task_done()
                except Exception as exc:
                    logger.error("Playback worker failed: %s", exc)
                    play_errors.append(exc)
                    audio_queue.task_done()
                    break

        # 启动工作线程
        tts_thread = threading.Thread(target=tts_worker, name="TTS-Worker", daemon=True)
        play_thread = threading.Thread(target=playback_worker, name="Playback-Worker", daemon=True)
        tts_thread.start()
        play_thread.start()

        # -------------------------------------------------------------
        # 3. 主线程：生产者（消费 LLM Token 流并切句）
        # -------------------------------------------------------------
        try:
            self.splitter.reset()
            for token in token_stream:
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                    logger.debug("Time to First Token (TTFT): %.1f ms", (first_token_time - start_time) * 1000)

                full_text_parts.append(token)
                if on_token_callback:
                    on_token_callback(token)

                for sentence in self.splitter.process_token(token):
                    if on_sentence_callback:
                        on_sentence_callback(sentence)
                    sentence_queue.put(sentence)

            # Token 流读取完毕，刷新剩余句子
            for remaining_sentence in self.splitter.flush():
                if on_sentence_callback:
                    on_sentence_callback(remaining_sentence)
                sentence_queue.put(remaining_sentence)

        finally:
            # 放入结束标记
            sentence_queue.put(None)

        # 等待所有后台任务完成
        tts_thread.join()
        play_thread.join()

        if tts_errors:
            logger.warning("TTS pipeline encountered errors: %s", tts_errors)
        if play_errors:
            logger.warning("Playback pipeline encountered errors: %s", play_errors)

        full_text = "".join(full_text_parts).strip()
        end_time = time.perf_counter()
        total_time_ms = (end_time - start_time) * 1000
        first_token_latency_ms = (
            (first_token_time - start_time) * 1000 if first_token_time else 0.0
        )
        first_audio_latency_ms = (
            (first_audio_time - start_time) * 1000 if first_audio_time else 0.0
        )

        return StreamPipelineResult(
            full_text=full_text,
            tts_characters=total_tts_chars,
            first_token_latency_ms=first_token_latency_ms,
            first_audio_latency_ms=first_audio_latency_ms,
            total_time_ms=total_time_ms,
            audio_chunks=collected_audio_chunks,
        )
