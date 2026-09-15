"""Azure OpenAI client wrapper."""
# 使用 OpenAI SDK 调用 Azure OpenAI，便于后续计费统计与替换
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import httpx
from openai import AzureOpenAI

from .logger import get_logger
from .web_search import WEB_SEARCH_TOOL_DEFINITION, WebSearchEngine

logger = get_logger("llm")


@dataclass
class Message:
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"role": self.role}
        if self.content is not None:
            data["content"] = self.content
        if self.tool_calls is not None:
            data["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            data["name"] = self.name
        return data


@dataclass
class LLMResponse:
    text: str
    usage: Dict[str, Any] | None = None
    model: str | None = None
    searched: bool = False
    search_queries: List[str] = field(default_factory=list)


class LLMClientProtocol:
    """LLM 客户端通用抽象协议（支持 AzureLLMClient 与 ResponsesAPIClientAdapter）"""

    def chat(
        self,
        messages: List[Message],
        *,
        temperature: float = 1.0,
        max_tokens: int | None = 512,
        stop: Iterable[str] | None = None,
    ) -> LLMResponse:
        ...

    def chat_stream(
        self,
        messages: List[Message],
        *,
        temperature: float = 1.0,
        max_tokens: int | None = 512,
        stop: Iterable[str] | None = None,
    ) -> Iterable[str]:
        """流式返回生成的文本块 (Tokens)"""
        ...


class AzureLLMClient:
    """Handles chat completion requests using OpenAI SDK."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str,
        *,
        search_engine: Optional[WebSearchEngine] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Azure OpenAI API key is required")

        logger.info(
            "Initializing Azure LLM client: endpoint=%s, deployment=%s, web_search=%s",
            endpoint,
            deployment,
            bool(search_engine),
        )

        # 禁用代理和环境变量，避免企业网络环境的代理配置冲突
        http_client = httpx.Client(
            timeout=timeout,
            trust_env=False,  # 忽略系统代理设置
        )

        # 使用 AzureOpenAI SDK，配置 Azure endpoint
        self.client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
            http_client=http_client,
        )
        self.deployment = deployment
        self.api_version = api_version
        self.search_engine = search_engine

    def chat(
        self,
        messages: List[Message],
        *,
        temperature: float = 1.0,  # 改为 1.0 以符合模型要求
        max_tokens: int | None = 512,
        stop: Iterable[str] | None = None,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        searched = False
        search_queries: List[str] = []

        # 拷贝消息列表以支持内部多轮工具调用往返
        current_messages = [msg.to_dict() for msg in messages]

        # 调用 OpenAI SDK
        try:
            # 构建基础参数
            params: Dict[str, Any] = {
                "model": self.deployment,
                "messages": current_messages,
                "max_completion_tokens": max_tokens,
            }

            if temperature != 1.0:
                params["temperature"] = temperature

            if stop:
                params["stop"] = list(stop)

            # 如果挂载了搜索引擎，注册 web_search 工具
            if self.search_engine:
                params["tools"] = [WEB_SEARCH_TOOL_DEFINITION]
                params["tool_choice"] = "auto"

            completion = self.client.chat.completions.create(**params)

            # 累计首轮 usage 信息
            if completion.usage:
                total_prompt_tokens += completion.usage.prompt_tokens or 0
                total_completion_tokens += completion.usage.completion_tokens or 0
                total_tokens += completion.usage.total_tokens or 0

            choice = completion.choices[0]
            message = choice.message

            # 检查模型是否决定调用函数（Tool Calling）
            if message.tool_calls and self.search_engine:
                searched = True
                # 把模型的回复（含 tool_calls）追加到当前上下文
                assistant_tool_msg = {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
                current_messages.append(assistant_tool_msg)

                # 执行工具调用并收集结果
                for tool_call in message.tool_calls:
                    func_name = tool_call.function.name
                    func_args_str = tool_call.function.arguments
                    tool_call_id = tool_call.id

                    if func_name == "web_search":
                        try:
                            parsed_args = json.loads(func_args_str)
                            query = parsed_args.get("query", "")
                        except Exception as parse_err:
                            logger.warning("解析 web_search 参数失败: %s, 原始参数: %s", parse_err, func_args_str)
                            query = func_args_str

                        search_queries.append(query)
                        logger.info("Triggered web_search tool: query='%s'", query)
                        search_result_text = self.search_engine.execute(query)

                        # 将工具执行结果作为 role="tool" 追加到上下文
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": search_result_text,
                        })

                # 第二轮调用：让模型结合搜索结果生成最终回答
                followup_params: Dict[str, Any] = {
                    "model": self.deployment,
                    "messages": current_messages,
                    "max_completion_tokens": max_tokens,
                }
                if temperature != 1.0:
                    followup_params["temperature"] = temperature
                if stop:
                    followup_params["stop"] = list(stop)

                second_completion = self.client.chat.completions.create(**followup_params)

                # 累加第二轮 Token 消耗
                if second_completion.usage:
                    total_prompt_tokens += second_completion.usage.prompt_tokens or 0
                    total_completion_tokens += second_completion.usage.completion_tokens or 0
                    total_tokens += second_completion.usage.total_tokens or 0

                content = second_completion.choices[0].message.content or ""
            else:
                content = message.content or ""

            usage = {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens,
            }

            logger.debug("LLM response: tokens=%s, model=%s, searched=%s", usage, self.deployment, searched)
            return LLMResponse(
                text=content.strip(),
                usage=usage,
                model=self.deployment,
                searched=searched,
                search_queries=search_queries,
            )
        except Exception as e:
            logger.error("Azure OpenAI call failed: %s", e)
            raise RuntimeError(f"Azure OpenAI error: {str(e)}") from e

    def chat_stream(
        self,
        messages: List[Message],
        *,
        temperature: float = 1.0,
        max_tokens: int | None = 512,
        stop: Iterable[str] | None = None,
    ) -> Iterable[str]:
        """流式调用 Azure OpenAI Chat Completions（支持 Tool Calling / 联网搜索）"""
        if not messages:
            raise ValueError("messages must not be empty")

        current_messages = [msg.to_dict() for msg in messages]

        params: Dict[str, Any] = {
            "model": self.deployment,
            "messages": current_messages,
            "max_completion_tokens": max_tokens,
            "stream": True,
        }

        if temperature != 1.0:
            params["temperature"] = temperature

        if stop:
            params["stop"] = list(stop)

        # 如果挂载了搜索引擎，注册 web_search 工具
        if self.search_engine:
            params["tools"] = [WEB_SEARCH_TOOL_DEFINITION]
            params["tool_choice"] = "auto"

        try:
            stream = self.client.chat.completions.create(**params)
            tool_calls_map: Dict[int, Dict[str, Any]] = {}
            has_tool_call = False

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    has_tool_call = True
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": tc.id or "",
                                "type": tc.type or "function",
                                "function": {
                                    "name": tc.function.name or "" if tc.function else "",
                                    "arguments": tc.function.arguments or "" if tc.function else "",
                                },
                            }
                        else:
                            if tc.id:
                                tool_calls_map[idx]["id"] += tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_map[idx]["function"]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_map[idx]["function"]["arguments"] += tc.function.arguments
                elif delta.content:
                    yield delta.content

            # 如果检测到工具调用且配置了搜索引擎，执行搜索并触发第二轮流式生成
            if has_tool_call and self.search_engine and tool_calls_map:
                tool_calls = list(tool_calls_map.values())
                current_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                })

                for tc in tool_calls:
                    func_name = tc["function"]["name"]
                    func_args_str = tc["function"]["arguments"]
                    tool_call_id = tc["id"]

                    if func_name == "web_search":
                        try:
                            parsed_args = json.loads(func_args_str)
                            query = parsed_args.get("query", "")
                        except Exception as parse_err:
                            logger.warning("解析 web_search 参数失败: %s, 原始参数: %s", parse_err, func_args_str)
                            query = func_args_str

                        logger.info("Triggered web_search tool (stream): query='%s'", query)
                        search_result_text = self.search_engine.execute(query)

                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": search_result_text,
                        })

                followup_params: Dict[str, Any] = {
                    "model": self.deployment,
                    "messages": current_messages,
                    "max_completion_tokens": max_tokens,
                    "stream": True,
                }
                if temperature != 1.0:
                    followup_params["temperature"] = temperature
                if stop:
                    followup_params["stop"] = list(stop)

                second_stream = self.client.chat.completions.create(**followup_params)
                for chunk in second_stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            yield delta.content

        except Exception as e:
            logger.error("Azure OpenAI stream failed: %s", e)
            raise RuntimeError(f"Azure OpenAI stream error: {str(e)}") from e
