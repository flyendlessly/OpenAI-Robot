"""Azure OpenAI / Azure AI Services implementation for Responses API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import httpx
from openai import AzureOpenAI, OpenAI

from ..logger import get_logger
from .base import BaseResponsesProvider, ResponseResult, parse_response_output

logger = get_logger("responses_api.azure")


class AzureResponsesProvider(BaseResponsesProvider):
    """Azure Responses API 适配器

    支持两种接入方式：
    1. AzureOpenAI SDK 原生方式 (azure_endpoint + api_version)
    2. 通用 OpenAI(base_url=https://xxx.services.ai.azure.com/openai/v1, api_key=...)
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str = "2025-01-01-preview",
        *,
        timeout: float = 30.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            raise ValueError("Azure API key is required")
        if not endpoint:
            raise ValueError("Azure endpoint is required")

        self.deployment = deployment
        self.endpoint = endpoint
        self.api_version = api_version

        # Azure 官方规定 Responses API 必须使用 2025-03-01-preview 及以上版本
        if not api_version or api_version < "2025-03-01-preview":
            effective_api_version = "2025-03-01-preview"
            logger.info("Auto-upgrading Azure api_version to '%s' for Responses API", effective_api_version)
        else:
            effective_api_version = api_version

        self.api_version = effective_api_version

        if http_client is None:
            http_client = httpx.Client(timeout=timeout, trust_env=False)

        # 智能判定接入形态：如果 endpoint 包含 /openai/v1，使用标准 OpenAI 客户端；否则使用 AzureOpenAI
        endpoint_clean = endpoint.rstrip("/")
        if endpoint_clean.endswith("/openai/v1") or "/services.ai.azure.com" in endpoint_clean:
            base_url = endpoint_clean if endpoint_clean.endswith("/openai/v1") else f"{endpoint_clean}/openai/v1"
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
            )
            logger.info("Azure Responses Provider initialized via OpenAI base_url: %s", base_url)
        else:
            self.client = AzureOpenAI(
                api_version=effective_api_version,
                azure_endpoint=endpoint,
                api_key=api_key,
                http_client=http_client,
            )
            logger.info(
                "Azure Responses Provider initialized via AzureOpenAI: endpoint=%s, deployment=%s, api_version=%s",
                endpoint,
                deployment,
                effective_api_version,
            )

    def create_response(
        self,
        input_text: Union[str, List[Dict[str, Any]]],
        *,
        instructions: Optional[str] = None,
        enable_web_search: bool = False,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ResponseResult:
        """通过 Responses API 发起请求"""
        call_tools: List[Dict[str, Any]] = list(tools) if tools else []
        if enable_web_search:
            call_tools.append({"type": "web_search_preview"})

        request_kwargs: Dict[str, Any] = {
            "model": self.deployment,
            "input": input_text,
            **kwargs,
        }
        if instructions:
            request_kwargs["instructions"] = instructions
        if call_tools:
            request_kwargs["tools"] = call_tools
        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            request_kwargs["max_output_tokens"] = max_output_tokens

        logger.debug("Calling Azure responses.create with model=%s, web_search=%s", self.deployment, enable_web_search)

        response = self.client.responses.create(**request_kwargs)
        result = parse_response_output(response, default_model=self.deployment)
        if result.searched:
            logger.info("Azure Responses API executed native web_search_preview. Queries: %s", result.search_queries)
        return result
