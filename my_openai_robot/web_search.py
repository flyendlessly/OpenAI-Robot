"""Web Search tools and providers for Azure OpenAI."""
# 联网搜索模块：提供 DuckDuckGo / Bing / Tavily 等搜索引擎适配，并定义 OpenAI Tool Schema
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, List, Optional

import httpx

from .logger import get_logger

logger = get_logger("web_search")

# OpenAI Function Calling 标准格式定义
WEB_SEARCH_TOOL_DEFINITION: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "通过搜索引擎搜索互联网上的最新信息、实时资讯、天气、事实核查或专业知识。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "需要搜索的关键词或查询语句",
                }
            },
            "required": ["query"],
        },
    },
}


@dataclass
class SearchResultItem:
    """单个搜索结果条目"""
    title: str
    url: str
    snippet: str

    def to_dict(self) -> Dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class BaseSearchProvider(ABC):
    """搜索引擎抽象基类"""

    @abstractmethod
    def search(self, query: str, max_results: int = 3) -> List[SearchResultItem]:
        """执行搜索并返回标准结果列表"""
        pass


class DuckDuckGoSearchProvider(BaseSearchProvider):
    """DuckDuckGo 免费搜索提供者（无需 API Key）"""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def search(self, query: str, max_results: int = 3) -> List[SearchResultItem]:
        results: List[SearchResultItem] = []
        try:
            # 优先尝试 duckduckgo_search 库
            from duckduckgo_search import DDGS
            with DDGS(timeout=self.timeout) as ddgs:
                raw_results = list(ddgs.text(query, max_results=max_results))
                for item in raw_results:
                    results.append(
                        SearchResultItem(
                            title=item.get("title", ""),
                            url=item.get("href", item.get("link", "")),
                            snippet=item.get("body", item.get("snippet", "")),
                        )
                    )
            if results:
                return results
        except ImportError:
            logger.debug("未安装 duckduckgo_search 依赖，尝试降级抓取")
        except Exception as e:
            logger.warning("duckduckgo_search 调用异常 (%s)，尝试降级接口", e)

        # 降级方案 1：使用 Bing RSS 无密钥公共检索源
        try:
            bing_rss_provider = BingFreeSearchProvider(timeout=self.timeout)
            results = bing_rss_provider.search(query, max_results=max_results)
            if results:
                logger.info("DuckDuckGo 自动降级至公共搜索通道成功，获取到 %d 条结果", len(results))
                return results
        except Exception as exc:
            logger.debug("降级 Bing RSS 检索失败: %s", exc)

        # 降级方案 2：使用 DuckDuckGo Instant Answer API
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                resp = client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    abstract = data.get("AbstractText", "")
                    if abstract:
                        results.append(
                            SearchResultItem(
                                title=data.get("Heading", query),
                                url=data.get("AbstractURL", ""),
                                snippet=abstract,
                            )
                        )
                    for topic in data.get("RelatedTopics", [])[:max_results]:
                        if isinstance(topic, dict) and "Text" in topic:
                            results.append(
                                SearchResultItem(
                                    title=topic.get("Text", "")[:30],
                                    url=topic.get("FirstURL", ""),
                                    snippet=topic.get("Text", ""),
                                )
                            )
        except Exception as exc:
            logger.debug("DuckDuckGo Instant Answer 降级请求失败: %s", exc)

        return results


class BingFreeSearchProvider(BaseSearchProvider):
    """基于 Bing 公共检索源（无需 API Key，国内网络秒级直连）"""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def search(self, query: str, max_results: int = 3) -> List[SearchResultItem]:
        results: List[SearchResultItem] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False, headers=headers) as client:
                resp = client.get("https://cn.bing.com/search", params={"q": query, "format": "rss"})
                if resp.status_code == 200 and resp.content:
                    root = ET.fromstring(resp.content)
                    items = root.findall(".//item")
                    for item in items[:max_results]:
                        title = item.findtext("title") or ""
                        link = item.findtext("link") or ""
                        desc = item.findtext("description") or ""

                        # 过滤 HTML 标签并解码实体
                        clean_title = unescape(re.sub(r"<[^>]+>", "", title)).strip()
                        clean_desc = unescape(re.sub(r"<[^>]+>", "", desc)).strip()

                        if clean_title and link:
                            results.append(
                                SearchResultItem(
                                    title=clean_title,
                                    url=link,
                                    snippet=clean_desc,
                                )
                            )
        except Exception as e:
            logger.error("BingFreeSearchProvider 检索失败: %s", e)

        return results


class TavilySearchProvider(BaseSearchProvider):
    """Tavily AI 专为 LLM 设计的高质量搜索引擎 (支持 include_answer 及时效事实)"""

    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        if not api_key:
            raise ValueError("Tavily search provider 需要配置 API Key")
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, max_results: int = 3) -> List[SearchResultItem]:
        results: List[SearchResultItem] = []
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "advanced",  # 使用深度/高质量搜索
                        "include_answer": True,      # 包含 AI 预先提炼的事实答案
                    },
                )
                response.raise_for_status()
                data = response.json()

                # 如果 Tavily 直接提取出了针对该问题的即时事实摘要 (如天气、最新新闻)，优先放入结果首位
                direct_answer = data.get("answer")
                if direct_answer:
                    results.append(
                        SearchResultItem(
                            title="[Tavily Instant Answer]",
                            url="https://tavily.com",
                            snippet=direct_answer,
                        )
                    )

                for item in data.get("results", []):
                    results.append(
                        SearchResultItem(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            snippet=item.get("content", ""),
                        )
                    )
        except Exception as e:
            logger.error("Tavily 搜索请求失败: %s", e)
        return results


class BingSearchProvider(BaseSearchProvider):
    """Azure Bing Web Search API 提供者（需要 Azure 订阅 Key）"""

    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        if not api_key:
            raise ValueError("Bing search provider 需要配置 API Key")
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, max_results: int = 3) -> List[SearchResultItem]:
        results: List[SearchResultItem] = []
        try:
            headers = {"Ocp-Apim-Subscription-Key": self.api_key}
            params = {"q": query, "count": max_results, "textDecorations": False, "textFormat": "Raw"}
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.get(
                    "https://api.bing.microsoft.com/v7.0/search",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                web_pages = data.get("webPages", {}).get("value", [])
                for item in web_pages:
                    results.append(
                        SearchResultItem(
                            title=item.get("name", ""),
                            url=item.get("url", ""),
                            snippet=item.get("snippet", ""),
                        )
                    )
        except Exception as e:
            logger.error("Bing 搜索请求失败: %s", e)
        return results


class WebSearchEngine:
    """搜索执行引擎，管理 Provider 并格式化结果供 LLM 使用"""

    def __init__(
        self,
        provider: BaseSearchProvider,
        *,
        max_results: int = 3,
    ) -> None:
        self.provider = provider
        self.max_results = max_results

    def execute(self, query: str) -> str:
        """执行搜索并返回结构化文本结果"""
        logger.info("Executing web search query: '%s'", query)
        items = self.provider.search(query, max_results=self.max_results)
        if not items:
            logger.info("Search returned 0 results for query: '%s'", query)
            return json.dumps({"status": "no_results", "query": query, "results": []}, ensure_ascii=False)

        formatted_results = [item.to_dict() for item in items]
        logger.info("Search found %d results for query: '%s'", len(formatted_results), query)
        return json.dumps({"status": "success", "query": query, "results": formatted_results}, ensure_ascii=False)


def create_search_engine(settings: Any) -> Optional[WebSearchEngine]:
    """根据配置创建搜索引擎实例"""
    if not getattr(settings, "enabled", False):
        return None

    provider_name = getattr(settings, "provider", "duckduckgo").lower()
    timeout = getattr(settings, "timeout", 10.0)
    api_key = getattr(settings, "api_key", None) or ""
    max_results = getattr(settings, "max_results", 3)

    provider: BaseSearchProvider
    if provider_name in ("duckduckgo", "ddg"):
        provider = DuckDuckGoSearchProvider(timeout=timeout)
    elif provider_name in ("bing_free", "bing-free", "free_bing"):
        provider = BingFreeSearchProvider(timeout=timeout)
    elif provider_name == "tavily":
        if not api_key:
            logger.warning("启用 Tavily 搜索但未配置 WEB_SEARCH_API_KEY，搜索可能无法工作")
        provider = TavilySearchProvider(api_key=api_key, timeout=timeout)
    elif provider_name == "bing":
        if api_key:
            provider = BingSearchProvider(api_key=api_key, timeout=timeout)
        else:
            logger.info("未配置 Bing API Key，自动启用免 Key 公共检索源 (BingFreeSearchProvider)")
            provider = BingFreeSearchProvider(timeout=timeout)
    else:
        logger.warning("未知的搜索引擎类型: %s，降级为 DuckDuckGo", provider_name)
        provider = DuckDuckGoSearchProvider(timeout=timeout)

    logger.info("WebSearchEngine initialized: provider=%s, max_results=%d", provider_name, max_results)
    return WebSearchEngine(provider=provider, max_results=max_results)
