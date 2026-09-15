"""High-level orchestration for the voice assistant."""
# 对话管理：串联音频输入、语音服务与 LLM
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Union

from .audio_io import SoundDeviceSpeaker
from .child_safety import ChildSafetyFilter, ContentFilterResult
from .config import ChildSafetySettings
from .llm_client import AzureLLMClient, LLMClientProtocol, LLMResponse, Message
from .logger import get_logger
from .speech_service import SpeechResult, SpeechService
from .streaming.pipeline import StreamingAudioPipeline, StreamPipelineResult


@dataclass
class ConversationTurnResult:
    """语音对话的一次完整往返结果"""

    transcript: str
    response: LLMResponse
    audio_reply: Optional[bytes] = None
    # 计费信息
    stt_duration_seconds: float = 0.0  # STT 音频时长
    tts_characters: int = 0  # TTS 字符数


@dataclass
class ConversationManager:
    """维护上下文并驱动单轮交互"""

    llm_client: Union[AzureLLMClient, LLMClientProtocol]
    speech_service: SpeechService
    conversation_history: List[Message] = field(default_factory=list)
    system_prompt: Optional[str] = None
    safety_filter: Optional[ChildSafetyFilter] = None

    def __post_init__(self) -> None:
        if self.system_prompt:
            self.conversation_history.append(Message(role="system", content=self.system_prompt))

    def handle_turn(self, audio_input: bytes, *, synthesize: bool = True) -> ConversationTurnResult:
        """处理一轮音频输入，返回识别文本、LLM 回复与合成语音"""
        if not audio_input:
            raise ValueError("audio_input 不能为空")
        
        # STT: 语音识别
        stt_result: SpeechResult = self.speech_service.transcribe(audio_input)
        user_text = (stt_result.text or "").strip()
        stt_duration = stt_result.duration_seconds
        
        if not user_text:
            raise RuntimeError("语音识别未得到有效文本")
        
        filter_results: List[ContentFilterResult] = []
        
        # 第 1 层防护：输入预过滤（本地黑名单）
        if self.safety_filter:
            input_check = self.safety_filter.check_input(user_text)
            filter_results.append(input_check)
            
            if not input_check.is_safe:
                # 输入被拦截，返回安全回复
                safe_response_text = self.safety_filter.get_safe_response()
                logger.warning("儿童安全过滤: %s | 匹配关键词: %s", input_check.reason, input_check.matched_keywords)
                
                # 记录日志
                self.safety_filter.log_conversation(
                    user_input=user_text,
                    assistant_response=safe_response_text,
                    filter_results=filter_results,
                    metadata={"blocked": True, "layer": "input"},
                )
                
                # 返回安全回复
                audio_reply = None
                tts_characters = 0
                if synthesize:
                    audio_reply = self.speech_service.synthesize(safe_response_text)
                    tts_characters = len(safe_response_text)

                # 创建虚拟 LLM 响应
                safe_response = LLMResponse(
                    text=safe_response_text,
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    model="safety-filter",
                )
                return ConversationTurnResult(
                    transcript=user_text,
                    response=safe_response,
                    audio_reply=audio_reply,
                    stt_duration_seconds=stt_duration,
                    tts_characters=tts_characters,
                )
        
        # 正常流程：调用 LLM
        user_message = Message(role="user", content=user_text)
        self.conversation_history.append(user_message)
        
        # 第 2 层防护：System Prompt 引导（在 llm_client 中自动应用）
        response = self.llm_client.chat(self.conversation_history)
        
        assistant_message = Message(role="assistant", content=response.text)
        self.conversation_history.append(assistant_message)
        
        # 第 3 层防护：输出检查（Azure 过滤 + 本地黑名单）
        if self.safety_filter:
            # 检查回复内容
            output_check = self.safety_filter.check_output(
                response.text,
                response_data=getattr(response, "raw_response", None),
            )
            filter_results.append(output_check)
            
            if not output_check.is_safe:
                # 输出被拦截
                safe_response_text = self.safety_filter.get_safe_response()
                logger.warning("AI 回复被过滤: %s", output_check.reason)
                
                # 记录日志
                self.safety_filter.log_conversation(
                    user_input=user_text,
                    assistant_response=f"[FILTERED] {response.text}",
                    filter_results=filter_results,
                    metadata={"blocked": True, "layer": "output"},
                )
                
                # 替换为安全回复
                response = LLMResponse(
                    text=safe_response_text,
                    usage=response.usage,
                    model=response.model,
                )
                assistant_message = Message(role="assistant", content=safe_response_text)
                self.conversation_history[-1] = assistant_message
            else:
                # 通过过滤，记录正常日志
                self.safety_filter.log_conversation(
                    user_input=user_text,
                    assistant_response=response.text,
                    filter_results=filter_results,
                    metadata={"blocked": False},
                )
        
        # TTS: 语音合成
        audio_reply: Optional[bytes] = None
        tts_characters = 0
        if synthesize:
            audio_reply = self.speech_service.synthesize(response.text)
            tts_characters = len(response.text)  # 计算字符数
        
        return ConversationTurnResult(
            transcript=user_text,
            response=response,
            audio_reply=audio_reply,
            stt_duration_seconds=stt_duration,
            tts_characters=tts_characters,
        )

    def handle_turn_stream(
        self,
        audio_input: bytes,
        speaker: Optional[SoundDeviceSpeaker] = None,
        *,
        on_token_callback: Optional[Callable[[str], None]] = None,
        on_sentence_callback: Optional[Callable[[str], None]] = None,
        synthesize: bool = True,
        play_audio: bool = True,
    ) -> ConversationTurnResult:
        """流式处理一轮音频输入：LLM 生成 -> 分句 -> 边合成边播放 (降低 70%+ 延迟)"""
        if not audio_input:
            raise ValueError("audio_input 不能为空")

        # 1. STT 语音识别
        stt_result: SpeechResult = self.speech_service.transcribe(audio_input)
        user_text = (stt_result.text or "").strip()
        stt_duration = stt_result.duration_seconds

        if not user_text:
            raise RuntimeError("语音识别未得到有效文本")

        filter_results: List[ContentFilterResult] = []

        # 2. 第 1 层防护：输入预过滤（本地黑名单拦截）
        if self.safety_filter:
            input_check = self.safety_filter.check_input(user_text)
            filter_results.append(input_check)

            if not input_check.is_safe:
                safe_response_text = self.safety_filter.get_safe_response()
                logger.warning("儿童安全过滤: %s | 匹配关键词: %s", input_check.reason, input_check.matched_keywords)

                self.safety_filter.log_conversation(
                    user_input=user_text,
                    assistant_response=safe_response_text,
                    filter_results=filter_results,
                    metadata={"blocked": True, "layer": "input"},
                )

                audio_reply = None
                tts_characters = 0
                if synthesize:
                    audio_reply = self.speech_service.synthesize(safe_response_text)
                    tts_characters = len(safe_response_text)
                    if play_audio and speaker and audio_reply:
                        speaker.play(audio_reply)

                safe_response = LLMResponse(
                    text=safe_response_text,
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    model="safety-filter",
                )
                return ConversationTurnResult(
                    transcript=user_text,
                    response=safe_response,
                    audio_reply=audio_reply,
                    stt_duration_seconds=stt_duration,
                    tts_characters=tts_characters,
                )

        # 3. 正常流程：调用 LLM 流式生成
        user_message = Message(role="user", content=user_text)
        self.conversation_history.append(user_message)

        pipeline = StreamingAudioPipeline(
            speech_service=self.speech_service,
            speaker=speaker,
        )

        token_stream = self.llm_client.chat_stream(self.conversation_history)

        stream_result: StreamPipelineResult = pipeline.run(
            token_stream,
            on_token_callback=on_token_callback,
            on_sentence_callback=on_sentence_callback,
            synthesize=synthesize,
            play_audio=play_audio,
        )

        full_response_text = stream_result.full_text
        assistant_message = Message(role="assistant", content=full_response_text)
        self.conversation_history.append(assistant_message)

        # 4. 第 3 层防护：输出安全检查与记录
        if self.safety_filter:
            output_check = self.safety_filter.check_output(full_response_text)
            filter_results.append(output_check)

            if not output_check.is_safe:
                logger.warning("AI 流式回复触发安全策略: %s", output_check.reason)
                self.safety_filter.log_conversation(
                    user_input=user_text,
                    assistant_response=f"[FILTERED] {full_response_text}",
                    filter_results=filter_results,
                    metadata={"blocked": True, "layer": "output"},
                )
            else:
                self.safety_filter.log_conversation(
                    user_input=user_text,
                    assistant_response=full_response_text,
                    filter_results=filter_results,
                    metadata={"blocked": False},
                )

        # 合并所有音频块以供保存
        combined_audio = b"".join(stream_result.audio_chunks) if stream_result.audio_chunks else None

        # 估算或包装 LLMResponse
        response = LLMResponse(
            text=full_response_text,
            usage={
                "prompt_tokens": len(user_text) * 2,
                "completion_tokens": len(full_response_text) * 2,
                "total_tokens": (len(user_text) + len(full_response_text)) * 2,
            },
            model=getattr(self.llm_client, "deployment", getattr(self.llm_client, "model", "streaming")),
        )

        return ConversationTurnResult(
            transcript=user_text,
            response=response,
            audio_reply=combined_audio,
            stt_duration_seconds=stt_duration,
            tts_characters=stream_result.tts_characters,
        )
