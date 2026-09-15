"""Adapter to bridge BaseResponsesProvider into LLMClientProtocol for ConversationManager and CLI."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..llm_client import LLMResponse, Message
from ..logger import get_logger
from .base import BaseResponsesProvider

logger = get_logger("responses_api.adapter")


class ResponsesAPIClientAdapter:
    """将 Responses API Provider 适配为系统通用的 LLM Client 协议 (chat 接口)

    这样不论是 CLI 单轮调用，还是 ConversationManager 多轮语音对话，
    都可以无感知切换使用 Responses API (OpenAI 或 Azure 后端)。
    """

    def __init__(
        self,
        provider: BaseResponsesProvider,
        *,
        enable_web_search: bool = False,
    ) -> None:
        self.provider = provider
        self.enable_web_search = enable_web_search

    def chat(
        self,
        messages: List[Message],
        *,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        stop: Optional[Iterable[str]] = None,
    ) -> LLMResponse:
        """适配 chat 方法以符合 ConversationManager 和 CLI 规范"""
        if not messages:
            raise ValueError("messages must not be empty")

        # 从 messages 中拆分 instructions (system prompt) 和 input 消息
        instructions: Optional[str] = None
        input_list: List[Dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                if instructions is None:
                    instructions = msg.content or ""
                else:
                    instructions += f"\n{msg.content or ''}"
            else:
                input_list.append(msg.to_dict())

        # 如果只有一条 user 文本消息，简化入参
        input_param: Any = input_list
        if len(input_list) == 1 and input_list[0].get("role") == "user" and isinstance(input_list[0].get("content"), str):
            input_param = input_list[0]["content"]

        logger.debug("Adapting chat to Responses API: %d messages", len(messages))

        result = self.provider.create_response(
            input_text=input_param,
            instructions=instructions,
            enable_web_search=self.enable_web_search,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        return LLMResponse(
            text=result.text,
            usage=result.usage,
            model=result.model,
            searched=result.searched,
            search_queries=result.search_queries,
        )

    def chat_stream(
        self,
        messages: List[Message],
        *,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        stop: Optional[Iterable[str]] = None,
    ) -> Iterable[str]:
        """适配 chat_stream 方法以支持流式 Token 生成"""
        if not messages:
            raise ValueError("messages must not be empty")

        instructions: Optional[str] = None
        input_list: List[Dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                if instructions is None:
                    instructions = msg.content or ""
                else:
                    instructions += f"\n{msg.content or ''}"
            else:
                input_list.append(msg.to_dict())

        input_param: Any = input_list
        if len(input_list) == 1 and input_list[0].get("role") == "user" and isinstance(input_list[0].get("content"), str):
            input_param = input_list[0]["content"]

        logger.debug("Adapting chat_stream to Responses API: %d messages", len(messages))

        yield from self.provider.create_response_stream(
            input_text=input_param,
            instructions=instructions,
            enable_web_search=self.enable_web_search,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
