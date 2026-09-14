"""Base definitions and adapter interfaces for Responses API providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class ResponseResult:
    """Responses API 统一调用返回结果（领域模型）"""
    text: str
    usage: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    response_id: Optional[str] = None
    searched: bool = False
    search_queries: List[str] = field(default_factory=list)
    raw_response: Optional[Any] = None


def parse_response_output(response: Any, default_model: Optional[str] = None) -> ResponseResult:
    """统一解析 Responses API 的响应结构 (兼容 output[0]、output_text 等多种 SDK 输出格式)"""
    text_output = ""
    searched = False
    search_queries: List[str] = []

    # 1. 优先提取 output_text
    if hasattr(response, "output_text") and response.output_text:
        text_output = response.output_text
    # 2. 遍历 response.output 列表 (包含 message, web_search_call 等)
    elif hasattr(response, "output") and response.output:
        for item in response.output:
            # 字符串情况 (例如部分精简返回)
            if isinstance(item, str):
                text_output += item
                continue

            item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)

            if item_type == "message" or item_type is None:
                # 提取 message 中的 content
                content = getattr(item, "content", None) or (item.get("content") if isinstance(item, dict) else None)
                if isinstance(content, str):
                    text_output += content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, str):
                            text_output += part
                        elif hasattr(part, "text"):
                            text_output += getattr(part, "text", "") or ""
                        elif isinstance(part, dict) and "text" in part:
                            text_output += part["text"] or ""
            elif item_type == "web_search_call":
                searched = True
                action = getattr(item, "action", None) or (item.get("action") if isinstance(item, dict) else None)
                query = None
                if action:
                    query = getattr(action, "query", None) or (action.get("query") if isinstance(action, dict) else None)
                if not query:
                    query = getattr(item, "query", None) or (item.get("query") if isinstance(item, dict) else None)
                if query:
                    search_queries.append(str(query))

    # 3. 提取 Token Usage
    usage_dict = None
    if hasattr(response, "usage") and response.usage:
        u = response.usage
        usage_dict = {
            "prompt_tokens": getattr(u, "input_tokens", getattr(u, "prompt_tokens", 0)),
            "completion_tokens": getattr(u, "output_tokens", getattr(u, "completion_tokens", 0)),
            "total_tokens": getattr(u, "total_tokens", 0),
        }
    elif isinstance(response, dict) and "usage" in response:
        u = response["usage"]
        usage_dict = {
            "prompt_tokens": u.get("input_tokens", u.get("prompt_tokens", 0)),
            "completion_tokens": u.get("output_tokens", u.get("completion_tokens", 0)),
            "total_tokens": u.get("total_tokens", 0),
        }

    return ResponseResult(
        text=text_output.strip(),
        usage=usage_dict,
        model=getattr(response, "model", default_model),
        response_id=getattr(response, "id", None),
        searched=searched,
        search_queries=search_queries,
        raw_response=response,
    )


class BaseResponsesProvider(ABC):
    """Responses API 提供者抽象基类（策略模式统一接口）"""

    @abstractmethod
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
        """调用 Responses API 生成回复"""
        pass
