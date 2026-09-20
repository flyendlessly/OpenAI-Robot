"""Unit tests for the network retry mechanism and resilience features."""
import asyncio
import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from my_openai_robot.config import RetrySettings
from my_openai_robot.llm_client import AzureLLMClient, Message
from my_openai_robot.retry import (
    calculate_backoff,
    extract_retry_after,
    is_retryable_exception,
    retry_with_backoff,
)


class TestRetryMechanism(unittest.TestCase):
    """测试重试工具库的基础逻辑、退避算法与异常过滤分类"""

    def test_exception_classification(self):
        # 1. 可重试异常测试
        request_mock = httpx.Request("POST", "https://api.openai.com")
        response_429 = httpx.Response(429, request=request_mock)
        response_500 = httpx.Response(500, request=request_mock)
        response_503 = httpx.Response(503, request=request_mock)
        response_400 = httpx.Response(400, request=request_mock)
        response_401 = httpx.Response(401, request=request_mock)

        self.assertTrue(is_retryable_exception(RateLimitError("Rate limit", response=response_429, body=None)))
        self.assertTrue(is_retryable_exception(APIConnectionError(request=request_mock)))
        self.assertTrue(is_retryable_exception(APITimeoutError(request=request_mock)))
        self.assertTrue(is_retryable_exception(InternalServerError("Server error", response=response_500, body=None)))
        self.assertTrue(is_retryable_exception(httpx.ConnectTimeout("Connect timeout")))
        self.assertTrue(is_retryable_exception(httpx.HTTPStatusError("503 error", request=request_mock, response=response_503)))
        self.assertTrue(is_retryable_exception(RuntimeError("Azure Speech SDK error: WebSocket connection failed 1006")))
        self.assertTrue(is_retryable_exception(ConnectionResetError("Connection reset by peer")))

        # 2. 致命非重试异常（Fast-Fail）
        self.assertFalse(is_retryable_exception(AuthenticationError("Invalid API key", response=response_401, body=None)))
        self.assertFalse(is_retryable_exception(BadRequestError("Bad Request", response=response_400, body=None)))
        self.assertFalse(is_retryable_exception(ValueError("Invalid argument")))
        self.assertFalse(is_retryable_exception(TypeError("Type mismatch")))
        self.assertFalse(is_retryable_exception(httpx.HTTPStatusError("400 error", request=request_mock, response=response_400)))

    def test_calculate_backoff_no_jitter(self):
        # 验证基础指数增长（无抖动）: 0.5 * (2 ** (attempt - 1))
        d1 = calculate_backoff(1, initial_delay=0.5, max_delay=10.0, backoff_factor=2.0, jitter=False)
        d2 = calculate_backoff(2, initial_delay=0.5, max_delay=10.0, backoff_factor=2.0, jitter=False)
        d3 = calculate_backoff(3, initial_delay=0.5, max_delay=10.0, backoff_factor=2.0, jitter=False)

        self.assertAlmostEqual(d1, 0.5)
        self.assertAlmostEqual(d2, 1.0)
        self.assertAlmostEqual(d3, 2.0)

        # 验证不超过 max_delay 上限
        d_max = calculate_backoff(10, initial_delay=0.5, max_delay=3.0, backoff_factor=2.0, jitter=False)
        self.assertEqual(d_max, 3.0)

    def test_calculate_backoff_with_retry_after(self):
        # 验证服务端指定 Retry-After 优先级高于基础退避
        d = calculate_backoff(1, initial_delay=0.5, max_delay=10.0, backoff_factor=2.0, jitter=False, suggested_delay=4.2)
        self.assertAlmostEqual(d, 4.2)

    def test_extract_retry_after_header(self):
        request_mock = httpx.Request("POST", "https://api.openai.com")
        headers = httpx.Headers({"retry-after": "2.5"})
        response_with_header = httpx.Response(429, headers=headers, request=request_mock)
        exc = RateLimitError("Too Many Requests", response=response_with_header, body=None)

        extracted = extract_retry_after(exc)
        self.assertEqual(extracted, 2.5)

    @patch("time.sleep", return_value=None)
    def test_retry_decorator_transient_recovery(self, mock_sleep):
        """测试发生 2 次瞬态错误后第 3 次成功返回"""
        attempts = 0

        @retry_with_backoff(max_retries=3, initial_delay=0.1, jitter=False)
        def flaky_function():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise APIConnectionError(request=httpx.Request("GET", "https://test.com"))
            return "SUCCESS"

        result = flaky_function()
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(attempts, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep", return_value=None)
    def test_retry_decorator_fatal_fast_fail(self, mock_sleep):
        """测试鉴权等致命错误立即失败，不触发多余重试"""
        attempts = 0
        request_mock = httpx.Request("POST", "https://api.openai.com")
        response_401 = httpx.Response(401, request=request_mock)

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def auth_fail_function():
            nonlocal attempts
            attempts += 1
            raise AuthenticationError("Invalid key", response=response_401, body=None)

        with self.assertRaises(AuthenticationError):
            auth_fail_function()

        self.assertEqual(attempts, 1)  # 仅调用 1 次，立即抛出
        self.assertEqual(mock_sleep.call_count, 0)

    @patch("time.sleep", return_value=None)
    def test_retry_decorator_exhaustion(self, mock_sleep):
        """测试超过 max_retries 后最终抛出底层异常"""
        attempts = 0

        @retry_with_backoff(max_retries=2, initial_delay=0.1, jitter=False)
        def always_failing_function():
            nonlocal attempts
            attempts += 1
            raise APIConnectionError(request=httpx.Request("GET", "https://test.com"))

        with self.assertRaises(APIConnectionError):
            always_failing_function()

        self.assertEqual(attempts, 3)  # 1 次初试 + 2 次重试
        self.assertEqual(mock_sleep.call_count, 2)

    def test_async_retry_decorator(self):
        """测试对异步协程函数的支持"""
        attempts = 0

        @retry_with_backoff(max_retries=2, initial_delay=0.01, jitter=False)
        async def async_flaky():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise APIConnectionError(request=httpx.Request("GET", "https://test.com"))
            return "ASYNC_SUCCESS"

        result = asyncio.run(async_flaky())
        self.assertEqual(result, "ASYNC_SUCCESS")
        self.assertEqual(attempts, 2)


class TestAzureLLMClientRetry(unittest.TestCase):
    """测试 AzureLLMClient 中集成的重试机制"""

    @patch("time.sleep", return_value=None)
    @patch("my_openai_robot.llm_client.AzureOpenAI")
    def test_llm_client_chat_retries_transient_error(self, mock_azure_openai_cls, mock_sleep):
        mock_openai_client = MagicMock()
        mock_azure_openai_cls.return_value = mock_openai_client

        # 模拟第一次抛出连接异常，第二次成功返回
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="重试后回答成功", tool_calls=None))]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20, total_tokens=30)

        req = httpx.Request("POST", "https://test.com")
        mock_openai_client.chat.completions.create.side_effect = [
            APIConnectionError(request=req),
            mock_response,
        ]

        retry_settings = RetrySettings(enabled=True, max_retries=2, initial_delay=0.1)
        client = AzureLLMClient(
            endpoint="https://test.openai.azure.com/",
            api_key="test_key",
            deployment="gpt-4o",
            api_version="2024-02-15-preview",
            retry_settings=retry_settings,
        )

        res = client.chat([Message(role="user", content="你好")])
        self.assertEqual(res.text, "重试后回答成功")
        self.assertEqual(mock_openai_client.chat.completions.create.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
