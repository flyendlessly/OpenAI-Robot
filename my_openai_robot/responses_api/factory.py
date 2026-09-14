"""Factory for creating Responses API providers."""
from __future__ import annotations

from typing import Optional

from ..config import AppConfig
from ..logger import get_logger
from .azure_provider import AzureResponsesProvider
from .base import BaseResponsesProvider
from .openai_provider import OpenAIResponsesProvider

logger = get_logger("responses_api.factory")


def get_responses_provider(
    config: AppConfig,
    provider: Optional[str] = None,
    *,
    timeout: float = 30.0,
) -> BaseResponsesProvider:
    """根据配置或指定名称获取 Responses API 提供者实例

    Args:
        config: 应用配置对象 (AppConfig)
        provider: 可选覆盖的提供者名称 ("azure" | "openai")，不传则使用 config.responses_provider
        timeout: 超时时间（秒）

    Returns:
        BaseResponsesProvider 实例 (AzureResponsesProvider 或 OpenAIResponsesProvider)
    """
    target_provider = (provider or config.responses_provider or "azure").strip().lower()

    if target_provider == "azure":
        logger.info("Instantiating Azure Responses API Provider")
        return AzureResponsesProvider(
            endpoint=config.azure.endpoint,
            api_key=config.azure.api_key,
            deployment=config.azure.deployment,
            api_version=config.azure.api_version,
            timeout=timeout,
        )
    elif target_provider == "openai":
        logger.info("Instantiating OpenAI Responses API Provider")
        if not config.openai.api_key:
            raise ValueError(
                "OpenAI API key is missing. Please set OPENAI_API_KEY in your .env or environment."
            )
        return OpenAIResponsesProvider(
            api_key=config.openai.api_key,
            model=config.openai.model,
            base_url=config.openai.base_url,
            timeout=timeout,
        )
    else:
        raise ValueError(
            f"Unsupported Responses API provider: '{target_provider}'. Supported values: 'azure', 'openai'"
        )
