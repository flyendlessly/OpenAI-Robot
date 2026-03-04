"""High-level orchestration for the voice assistant."""
# 对话管理：串联音频输入、语音服务与 LLM
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .child_safety import ChildSafetyFilter, ContentFilterResult
from .config import ChildSafetySettings
from .llm_client import AzureLLMClient, LLMResponse, Message
from .speech_service import SpeechResult, SpeechService


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

    llm_client: AzureLLMClient
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
        stt_duration = getattr(stt_result, "duration_seconds", 0.0)  # 获取音频时长
        
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
                print(f"⚠ 儿童安全过滤: {input_check.reason}")
                print(f"  匹配关键词: {', '.join(input_check.matched_keywords)}")
                
                # 记录日志
                self.safety_filter.log_conversation(
                    user_input=user_text,
                    assistant_response=safe_response_text,
                    filter_results=filter_results,
                    metadata={"blocked": True, "layer": "input"},
                )
                
                # 返回安全回复
                audio_reply = None
                if synthesize:
                    audio_reply = self.speech_service.synthesize(safe_response_text)
                
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
                print(f"⚠ AI 回复被过滤: {output_check.reason}")
                
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
