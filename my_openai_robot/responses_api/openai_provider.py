"""OpenAI official implementation for Responses API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import httpx
from openai import OpenAI

from ..logger import get_logger
from .base import BaseResponsesProvider, ResponseResult, parse_response_output

logger = get_logger("responses_api.openai")


class OpenAIResponsesProvider(BaseResponsesProvider):
    """OpenAI 官方 Responses API 适配器"""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")

        self.model = model
        self.base_url = base_url

        if http_client is None:
            http_client = httpx.Client(timeout=timeout, trust_env=False)

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        logger.info(
            "OpenAI Responses Provider initialized: model=%s, base_url=%s",
            model,
            base_url or "default",
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
        """通过 OpenAI 官方 Responses API 发起请求"""
        call_tools: List[Dict[str, Any]] = list(tools) if tools else []
        if enable_web_search:
            call_tools.append({"type": "web_search_preview"})

        request_kwargs: Dict[str, Any] = {
            "model": self.model,
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

        logger.debug("Calling OpenAI responses.create with model=%s, web_search=%s", self.model, enable_web_search)

        response = self.client.responses.create(**request_kwargs)
        result = parse_response_output(response, default_model=self.model)
        if result.searched:
            logger.info("OpenAI Responses API executed native web_search_preview. Queries: %s", result.search_queries)
        return result
