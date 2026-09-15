"""Tests for AzureLLMClient including tool calling and stream tool calling."""
import json
import unittest
from unittest.mock import MagicMock, patch

from my_openai_robot.llm_client import AzureLLMClient, Message
from my_openai_robot.web_search import BaseSearchProvider, SearchResultItem, WebSearchEngine


class DummySearchProvider(BaseSearchProvider):
    def search(self, query: str, max_results: int = 3):
        return [
            SearchResultItem(
                title="Tesla Stock",
                url="https://finance.example.com/tsla",
                snippet=f"Tesla stock price is $380 for query: {query}",
            )
        ]


class TestAzureLLMClient(unittest.TestCase):
    def setUp(self):
        self.search_engine = WebSearchEngine(provider=DummySearchProvider(), max_results=2)

    @patch("my_openai_robot.llm_client.AzureOpenAI")
    def test_chat_stream_with_tool_calling(self, mock_azure_openai_cls):
        mock_openai_client = MagicMock()
        mock_azure_openai_cls.return_value = mock_openai_client

        # 模拟第 1 轮 Stream：返回 Tool Calling chunks
        mock_chunk_1 = MagicMock()
        mock_tc_1 = MagicMock()
        mock_tc_1.index = 0
        mock_tc_1.id = "call_abc123"
        mock_tc_1.type = "function"
        mock_tc_1.function.name = "web_search"
        mock_tc_1.function.arguments = '{"query": "'
        mock_chunk_1.choices = [MagicMock(delta=MagicMock(tool_calls=[mock_tc_1], content=None))]

        mock_chunk_2 = MagicMock()
        mock_tc_2 = MagicMock()
        mock_tc_2.index = 0
        mock_tc_2.id = None
        mock_tc_2.type = None
        mock_tc_2.function.name = None
        mock_tc_2.function.arguments = '特斯拉股价"}'
        mock_chunk_2.choices = [MagicMock(delta=MagicMock(tool_calls=[mock_tc_2], content=None))]

        first_stream = [mock_chunk_1, mock_chunk_2]

        # 模拟第 2 轮 Stream：结合搜索结果返回文本内容 chunks
        mock_reply_chunk_1 = MagicMock()
        mock_reply_chunk_1.choices = [MagicMock(delta=MagicMock(tool_calls=None, content="特斯拉现在的股价是"))]
        mock_reply_chunk_2 = MagicMock()
        mock_reply_chunk_2.choices = [MagicMock(delta=MagicMock(tool_calls=None, content="380美元。"))]

        second_stream = [mock_reply_chunk_1, mock_reply_chunk_2]

        mock_openai_client.chat.completions.create.side_effect = [first_stream, second_stream]

        client = AzureLLMClient(
            endpoint="https://test.openai.azure.com/",
            api_key="test_key",
            deployment="gpt-4o-mini",
            api_version="2024-02-15-preview",
            search_engine=self.search_engine,
        )

        messages = [Message(role="user", content="今天特斯拉股价")]
        stream_generator = client.chat_stream(messages)
        tokens = list(stream_generator)

        # 验证是否正确执行了两轮调用并获取到了第二轮流式 token
        self.assertEqual(mock_openai_client.chat.completions.create.call_count, 2)
        self.assertEqual("".join(tokens), "特斯拉现在的股价是380美元。")

        # 验证第 1 轮请求中携带了 tools
        first_call_kwargs = mock_openai_client.chat.completions.create.call_args_list[0][1]
        self.assertIn("tools", first_call_kwargs)
        self.assertEqual(first_call_kwargs["tools"][0]["function"]["name"], "web_search")

        # 验证第 2 轮请求中包含了 tool 的返回结果
        second_call_kwargs = mock_openai_client.chat.completions.create.call_args_list[1][1]
        second_messages = second_call_kwargs["messages"]
        self.assertTrue(any(m.get("role") == "tool" for m in second_messages))

    @patch("my_openai_robot.llm_client.AzureOpenAI")
    def test_chat_stream_without_tool_calling(self, mock_azure_openai_cls):
        mock_openai_client = MagicMock()
        mock_azure_openai_cls.return_value = mock_openai_client

        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock(delta=MagicMock(tool_calls=None, content="你好！有什么可以帮你的？"))]
        mock_openai_client.chat.completions.create.return_value = [mock_chunk]

        client = AzureLLMClient(
            endpoint="https://test.openai.azure.com/",
            api_key="test_key",
            deployment="gpt-4o-mini",
            api_version="2024-02-15-preview",
            search_engine=self.search_engine,
        )

        messages = [Message(role="user", content="你好")]
        tokens = list(client.chat_stream(messages))

        # 验证仅进行了一轮调用
        self.assertEqual(mock_openai_client.chat.completions.create.call_count, 1)
        self.assertEqual("".join(tokens), "你好！有什么可以帮你的？")


if __name__ == "__main__":
    unittest.main()
