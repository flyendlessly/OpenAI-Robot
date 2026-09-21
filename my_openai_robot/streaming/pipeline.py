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
    interrupted: bool = False            # 是否被唤醒词打断 (Barge-in)


class BargeInMonitor:
    """在流式播放期间持续监听麦克风唤醒词以实现随时打断 (Barge-in)"""

    def __init__(
        self,
        detector: Any,
        speaker: Optional[SoundDeviceSpeaker] = None,
        device: Optional[int] = None,
        on_barge_in: Optional[Callable[[int], None]] = None,
    ) -> None:
        self.detector = detector
        self.speaker = speaker
        self.device = device
        self.on_barge_in = on_barge_in
        self._stop_event = threading.Event()
        self._interrupt_event: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, interrupt_event: threading.Event) -> None:
        self._interrupt_event = interrupt_event
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, name="BargeIn-Monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _worker(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            return

        try:
            with sd.RawInputStream(
                samplerate=self.detector.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=self.detector.frame_length,
                device=self.device,
            ) as mic_stream:
                while not self._stop_event.is_set():
                    if self._interrupt_event and self._interrupt_event.is_set():
                        break
                    audio_frame, overflowed = mic_stream.read(self.detector.frame_length)
                    if self._stop_event.is_set():
                        break
                    if overflowed:
                        continue
                    detected, keyword_index = self.detector.process_audio(audio_frame.tobytes())
                    if detected:
                        logger.info("⚡ [Barge-in] 播放期间检测到唤醒词打断 (index=%d)", keyword_index)
                        if self._interrupt_event:
                            self._interrupt_event.set()
                        if self.speaker:
                            self.speaker.stop()
                        if self.on_barge_in:
                            try:
                                self.on_barge_in(keyword_index)
                            except Exception as cb_exc:
                                logger.warning("on_barge_in callback failed: %s", cb_exc)
                        break
        except Exception as exc:
            logger.debug("BargeInMonitor stream closed or error: %s", exc)


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
        interrupt_event: Optional[threading.Event] = None,
        barge_in_detector: Optional[Any] = None,
        barge_in_device: Optional[int] = None,
        on_barge_in_callback: Optional[Callable[[int], None]] = None,
    ) -> StreamPipelineResult:
        """执行流式流水线：消费 Token 流，分句并发合成 TTS，并连续推送到扬声器播放"""
        start_time = time.perf_counter()
        first_token_time: Optional[float] = None
        first_audio_time: Optional[float] = None

        if interrupt_event is None:
            interrupt_event = threading.Event()

        # 启动伴随唤醒词监听器（支持语音打断）
        barge_in_monitor: Optional[BargeInMonitor] = None
        if barge_in_detector is not None:
            barge_in_monitor = BargeInMonitor(
                detector=barge_in_detector,
                speaker=self.speaker,
                device=barge_in_device,
                on_barge_in=on_barge_in_callback,
            )
            barge_in_monitor.start(interrupt_event)

        full_text_parts: List[str] = []
        collected_audio_chunks: List[bytes] = []
        total_tts_chars = 0

        # 如果不需要合成或者不需要播放，进行降级快速处理
        if not synthesize:
            try:
                for token in token_stream:
                    if interrupt_event.is_set():
                        break
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    full_text_parts.append(token)
                    if on_token_callback:
                        on_token_callback(token)
            finally:
                if barge_in_monitor:
                    barge_in_monitor.stop()

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
                interrupted=interrupt_event.is_set(),
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
            while not interrupt_event.is_set():
                try:
                    sentence = sentence_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if sentence is None:
                        # 收到结束哨兵
                        audio_queue.put(None)
                        break

                    if interrupt_event.is_set():
                        break

                    if sentence.strip():
                        t0 = time.perf_counter()
                        audio_bytes = self.speech_service.synthesize(sentence)
                        elapsed_ms = (time.perf_counter() - t0) * 1000
                        logger.debug("TTS synthesized sentence '%s' (%d bytes, %.1f ms)", sentence, len(audio_bytes), elapsed_ms)
                        total_tts_chars += len(sentence)
                        audio_queue.put((sentence, audio_bytes))
                except Exception as exc:
                    if not interrupt_event.is_set():
                        logger.error("TTS worker failed on sentence: %s", exc)
                        tts_errors.append(exc)
                        audio_queue.put(None)
                    break
                finally:
                    sentence_queue.task_done()

        # -------------------------------------------------------------
        # 2. 消费者线程 2：音频播放
        # -------------------------------------------------------------
        def playback_worker() -> None:
            nonlocal first_audio_time
            while not interrupt_event.is_set():
                try:
                    item = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if item is None:
                        break

                    if interrupt_event.is_set():
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
                        if play_audio and self.speaker and not interrupt_event.is_set():
                            self.speaker.play(audio_bytes)
                except Exception as exc:
                    if not interrupt_event.is_set():
                        logger.error("Playback worker failed: %s", exc)
                        play_errors.append(exc)
                    break
                finally:
                    audio_queue.task_done()

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
                if interrupt_event.is_set():
                    logger.info("⚡ [Barge-in] LLM Token 生成流被唤醒词打断")
                    break

                if first_token_time is None:
                    first_token_time = time.perf_counter()
                    logger.debug("Time to First Token (TTFT): %.1f ms", (first_token_time - start_time) * 1000)

                full_text_parts.append(token)
                if on_token_callback:
                    on_token_callback(token)

                for sentence in self.splitter.process_token(token):
                    if interrupt_event.is_set():
                        break
                    if on_sentence_callback:
                        on_sentence_callback(sentence)
                    sentence_queue.put(sentence)

            # Token 流读取完毕，刷新剩余句子
            if not interrupt_event.is_set():
                for remaining_sentence in self.splitter.flush():
                    if interrupt_event.is_set():
                        break
                    if on_sentence_callback:
                        on_sentence_callback(remaining_sentence)
                    sentence_queue.put(remaining_sentence)

        finally:
            if interrupt_event.is_set():
                if self.speaker:
                    self.speaker.stop()
                while not sentence_queue.empty():
                    try:
                        sentence_queue.get_nowait()
                        sentence_queue.task_done()
                    except Exception:
                        break
                while not audio_queue.empty():
                    try:
                        audio_queue.get_nowait()
                        audio_queue.task_done()
                    except Exception:
                        break
                # 打断时快速塞入终止哨兵
                try:
                    sentence_queue.put_nowait(None)
                except Exception:
                    pass
                try:
                    audio_queue.put_nowait(None)
                except Exception:
                    pass
            else:
                # 正常结束：仅需向 sentence_queue 传递哨兵，由 tts_worker 级联传递到 audio_queue
                sentence_queue.put(None)

            if barge_in_monitor:
                barge_in_monitor.stop()

        # 等待后台任务完成：确保 TTS 合成与音频全部播放完毕（支持正常播放完或打断迅速退出）
        tts_thread.join(timeout=60.0)
        play_thread.join(timeout=180.0)

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
            interrupted=interrupt_event.is_set(),
        )
