"""High-level orchestration for the voice assistant."""
# 对话管理：串联音频输入、语音服务与 LLM
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .llm_client import AzureLLMClient, LLMResponse, Message
from .speech_service import SpeechResult, SpeechService


@dataclass
class ConversationTurnResult:
    """语音对话的一次完整往返结果"""

    transcript: str
    response: LLMResponse
    audio_reply: Optional[bytes] = None


@dataclass
class ConversationManager:
    """维护上下文并驱动单轮交互"""

    llm_client: AzureLLMClient
    speech_service: SpeechService
    conversation_history: List[Message] = field(default_factory=list)
    system_prompt: Optional[str] = None

    def __post_init__(self) -> None:
        if self.system_prompt:
            self.conversation_history.append(Message(role="system", content=self.system_prompt))

    def handle_turn(self, audio_input: bytes, *, synthesize: bool = True) -> ConversationTurnResult:
        """处理一轮音频输入，返回识别文本、LLM 回复与合成语音"""
        if not audio_input:
            raise ValueError("audio_input 不能为空")
        stt_result: SpeechResult = self.speech_service.transcribe(audio_input)
        user_text = (stt_result.text or "").strip()
        if not user_text:
            raise RuntimeError("语音识别未得到有效文本")
        user_message = Message(role="user", content=user_text)
        self.conversation_history.append(user_message)
        response = self.llm_client.chat(self.conversation_history)
        assistant_message = Message(role="assistant", content=response.text)
        self.conversation_history.append(assistant_message)
        audio_reply: Optional[bytes] = None
        if synthesize:
            audio_reply = self.speech_service.synthesize(response.text)
        return ConversationTurnResult(
            transcript=user_text,
            response=response,
            audio_reply=audio_reply,
        )
