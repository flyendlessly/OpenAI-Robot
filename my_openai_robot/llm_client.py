"""Azure OpenAI client wrapper."""
# 使用 OpenAI SDK 调用 Azure OpenAI，便于后续计费统计与替换
from __future__ import annotations

import httpx
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from openai import AzureOpenAI


@dataclass
class Message:
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    text: str
    usage: Dict[str, Any] | None = None


class AzureLLMClient:
    """Handles chat completion requests using OpenAI SDK."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Azure OpenAI API key is required")
        
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
        
        # 调用 OpenAI SDK
        try:
            # 构建参数，某些模型只支持特定参数
            params = {
                "model": self.deployment,
                "messages": [msg.to_dict() for msg in messages],
                "max_completion_tokens": max_tokens,
            }
            
            # 只有非默认值才传递 temperature（某些模型只支持默认值 1）
            if temperature != 1.0:
                params["temperature"] = temperature
            
            if stop:
                params["stop"] = list(stop)
            
            completion = self.client.chat.completions.create(**params)
            
            # 提取响应内容
            content = completion.choices[0].message.content or ""
            
            # 提取 usage 信息用于计费
            usage = None
            if completion.usage:
                usage = {
                    "prompt_tokens": completion.usage.prompt_tokens,
                    "completion_tokens": completion.usage.completion_tokens,
                    "total_tokens": completion.usage.total_tokens,
                }
            
            return LLMResponse(text=content.strip(), usage=usage)
        except Exception as e:
            raise RuntimeError(f"Azure OpenAI error: {str(e)}") from e
