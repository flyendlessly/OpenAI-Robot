"""Responses API module for unified Azure OpenAI and OpenAI official API integration."""
from .adapter import ResponsesAPIClientAdapter
from .azure_provider import AzureResponsesProvider
from .base import BaseResponsesProvider, ResponseResult, parse_response_output
from .factory import get_responses_provider
from .openai_provider import OpenAIResponsesProvider

__all__ = [
    "BaseResponsesProvider",
    "AzureResponsesProvider",
    "OpenAIResponsesProvider",
    "ResponsesAPIClientAdapter",
    "ResponseResult",
    "parse_response_output",
    "get_responses_provider",
]
