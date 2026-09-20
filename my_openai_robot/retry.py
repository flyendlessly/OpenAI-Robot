"""Robust network and API retry mechanism with exponential backoff and jitter."""
from __future__ import annotations

import asyncio
import functools
import random
import time
from typing import Any, Callable, Optional, Tuple, Type, TypeVar, Union, cast

import httpx

from .logger import get_logger

logger = get_logger("retry")

# 引入 OpenAI SDK 常见异常（如果环境支持）
try:
    from openai import (
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
    )
    _OPENAI_INSTALLED = True
except ImportError:  # pragma: no cover
    APIConnectionError = Exception  # type: ignore
    APITimeoutError = Exception  # type: ignore
    AuthenticationError = Exception  # type: ignore
    BadRequestError = Exception  # type: ignore
    InternalServerError = Exception  # type: ignore
    NotFoundError = Exception  # type: ignore
    PermissionDeniedError = Exception  # type: ignore
    RateLimitError = Exception  # type: ignore
    _OPENAI_INSTALLED = False

F = TypeVar("F", bound=Callable[..., Any])

# 默认可重试的异常类型元组
DEFAULT_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    ConnectionResetError,
    TimeoutError,
)

# 致命（不可重试）的异常类型元组，命中即快速失败 (Fast-Fail)
FATAL_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    AuthenticationError,
    PermissionDeniedError,
    BadRequestError,
    NotFoundError,
    ValueError,
    TypeError,
)


def is_retryable_exception(exc: Exception) -> bool:
    """判断异常是否属于可重试的瞬态网络/服务端抖动异常

    - 致命异常 (401 鉴权失败, 403 权限不足, 400 参数错误等) 立即返回 False
    - HTTP 状态码为 408, 429 或 5xx 时返回 True
    - 瞬态网络断开、超时等返回 True
    - Azure Speech SDK 取消详情中指示网络中断或服务繁忙时返回 True
    """
    if not isinstance(exc, Exception):
        return False

    # 1. 快速失败：致命非瞬态异常直接拒绝重试
    if _OPENAI_INSTALLED and isinstance(exc, FATAL_EXCEPTIONS):
        return False

    # 2. HTTP 状态错误检查
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in {408, 429} or code >= 500:
            return True
        return False

    # 3. 标准连接与超时异常
    if isinstance(exc, DEFAULT_RETRYABLE_EXCEPTIONS):
        return True

    # 4. Azure Speech SDK 异常特征检查
    exc_str = str(exc).lower()
    if any(keyword in exc_str for keyword in (
        "connection failed",
        "connection timeout",
        "websocket",
        "service unavailable",
        "too many requests",
        "transient",
        "timeout",
        "1006",  # WebSocket abnormal closure
        "spxerr_connection_failed",
    )):
        return True

    return False


def extract_retry_after(exc: Exception) -> Optional[float]:
    """尝试从异常中提取服务端返回的 Retry-After 秒数"""
    # 检查 OpenAI 异常附带的 response
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers:
            retry_after_str = headers.get("retry-after") or headers.get("Retry-After")
            if retry_after_str:
                try:
                    return float(retry_after_str)
                except ValueError:
                    pass
    return None


def calculate_backoff(
    attempt: int,
    initial_delay: float,
    max_delay: float,
    backoff_factor: float,
    jitter: bool = True,
    suggested_delay: Optional[float] = None,
) -> float:
    """计算指数退避等待时长（附带 Full Jitter 抖动以避免惊群效应）"""
    if suggested_delay is not None and suggested_delay > 0:
        base = min(max_delay, suggested_delay)
    else:
        base = min(max_delay, initial_delay * (backoff_factor ** (attempt - 1)))

    if jitter:
        # Full Jitter: 在 [0.5 * base, 1.5 * base] 区间均匀随机
        delay = base * (0.5 + random.random())
    else:
        delay = base

    return max(0.01, min(max_delay, delay))


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 0.5,
    max_delay: float = 5.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    is_retryable: Optional[Callable[[Exception], bool]] = None,
) -> Callable[[F], F]:
    """函数重试装饰器，同时兼容同步与异步函数

    Args:
        max_retries: 最大重试次数（总调用次数 = 1 + max_retries）
        initial_delay: 初始等待时长（秒）
        max_delay: 最大等待上限（秒）
        backoff_factor: 指数乘数
        jitter: 是否启用随机抖动
        is_retryable: 自定义可重试断言函数，默认使用 is_retryable_exception
    """
    predicate = is_retryable or is_retryable_exception

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            total_attempts = max(1, 1 + max_retries)

            for attempt in range(1, total_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    # 如果达到最大重试次数，或者该异常不可重试，则直接抛出
                    if attempt >= total_attempts or not predicate(exc):
                        if attempt > 1:
                            logger.error(
                                "调用 %s 经过 %d 次尝试后终态失败: %s",
                                func.__name__,
                                attempt,
                                exc,
                            )
                        raise

                    suggested_delay = extract_retry_after(exc)
                    sleep_time = calculate_backoff(
                        attempt,
                        initial_delay,
                        max_delay,
                        backoff_factor,
                        jitter=jitter,
                        suggested_delay=suggested_delay,
                    )
                    logger.warning(
                        "调用 %s 发生瞬态异常 (%s: %s)，第 %d/%d 次重试，等待 %.2fs...",
                        func.__name__,
                        type(exc).__name__,
                        exc,
                        attempt,
                        total_attempts - 1,
                        sleep_time,
                    )
                    time.sleep(sleep_time)

            if last_exc:
                raise last_exc

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            total_attempts = max(1, 1 + max_retries)

            for attempt in range(1, total_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt >= total_attempts or not predicate(exc):
                        if attempt > 1:
                            logger.error(
                                "异步调用 %s 经过 %d 次尝试后终态失败: %s",
                                func.__name__,
                                attempt,
                                exc,
                            )
                        raise

                    suggested_delay = extract_retry_after(exc)
                    sleep_time = calculate_backoff(
                        attempt,
                        initial_delay,
                        max_delay,
                        backoff_factor,
                        jitter=jitter,
                        suggested_delay=suggested_delay,
                    )
                    logger.warning(
                        "异步调用 %s 发生瞬态异常 (%s: %s)，第 %d/%d 次重试，等待 %.2fs...",
                        func.__name__,
                        type(exc).__name__,
                        exc,
                        attempt,
                        total_attempts - 1,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)

            if last_exc:
                raise last_exc

        if asyncio.iscoroutinefunction(func):
            return cast(F, async_wrapper)
        return cast(F, sync_wrapper)

    return decorator
