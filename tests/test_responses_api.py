"""Tests for Responses API module, adapter and factory switching."""
import unittest
from unittest.mock import MagicMock, patch

from my_openai_robot.config import AppConfig, AzureSettings, OpenAISettings
from my_openai_robot.llm_client import Message
from my_openai_robot.responses_api import (
    AzureResponsesProvider,
    BaseResponsesProvider,
    OpenAIResponsesProvider,
    ResponsesAPIClientAdapter,
    ResponseResult,
    get_responses_provider,
    parse_response_output,
)


def create_dummy_config(provider="azure", openai_key="sk-test", azure_key="az-test"):
    return AppConfig(
        responses_provider=provider,
        azure=AzureSettings(
            endpoint="https://test.openai.azure.com/",
            api_key=azure_key,
            deployment="gpt-4o",
            api_version="2025-01-01-preview",
        ),
        openai=OpenAISettings(
            api_key=openai_key,
            model="gpt-4o",
            base_url=None,
        ),
    )


class TestResponsesAPI(unittest.TestCase):
    def test_factory_creates_azure_provider(self):
        config = create_dummy_config(provider="azure")
        provider = get_responses_provider(config)
        self.assertIsInstance(provider, AzureResponsesProvider)
        self.assertIsInstance(provider, BaseResponsesProvider)
        self.assertEqual(provider.deployment, "gpt-4o")
        self.assertEqual(provider.endpoint, "https://test.openai.azure.com/")

    def test_factory_creates_openai_provider(self):
        config = create_dummy_config(provider="openai")
        provider = get_responses_provider(config)
        self.assertIsInstance(provider, OpenAIResponsesProvider)
        self.assertIsInstance(provider, BaseResponsesProvider)
        self.assertEqual(provider.model, "gpt-4o")

    def test_factory_explicit_override(self):
        config = create_dummy_config(provider="azure")
        provider = get_responses_provider(config, provider="openai")
        self.assertIsInstance(provider, OpenAIResponsesProvider)

    def test_factory_openai_missing_key_raises_error(self):
        config = create_dummy_config(provider="openai", openai_key=None)
        with self.assertRaises(ValueError) as ctx:
            get_responses_provider(config)
        self.assertIn("OpenAI API key is missing", str(ctx.exception))

    def test_factory_unsupported_provider_raises_error(self):
        config = create_dummy_config(provider="unknown_provider")
        with self.assertRaises(ValueError) as ctx:
            get_responses_provider(config)
        self.assertIn("Unsupported Responses API provider", str(ctx.exception))

    def test_parse_response_output_with_output_list(self):
        # 模拟官方 response.output[0] 包含 message 结构的输出
        mock_msg_item = MagicMock()
        mock_msg_item.type = "message"
        mock_part = MagicMock()
        mock_part.type = "text"
        mock_part.text = "France is Paris."
        mock_msg_item.content = [mock_part]

        mock_resp = MagicMock()
        mock_resp.output_text = None
        mock_resp.output = [mock_msg_item]
        mock_resp.id = "resp_abc"
        mock_resp.model = "gpt-4.1-mini"
        mock_resp.usage.input_tokens = 8
        mock_resp.usage.output_tokens = 5
        mock_resp.usage.total_tokens = 13

        result = parse_response_output(mock_resp)
        self.assertEqual(result.text, "France is Paris.")
        self.assertEqual(result.model, "gpt-4.1-mini")
        self.assertEqual(result.usage["total_tokens"], 13)

    @patch("my_openai_robot.responses_api.azure_provider.AzureOpenAI")
    def test_azure_provider_create_response(self, mock_azure_client_cls):
        mock_client = MagicMock()
        mock_azure_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.output_text = "你好！我是 Azure Responses API"
        mock_response.id = "resp_123"
        mock_response.model = "gpt-4o"
        mock_response.usage.input_tokens = 15
        mock_response.usage.output_tokens = 25
        mock_response.usage.total_tokens = 40
        mock_client.responses.create.return_value = mock_response

        provider = AzureResponsesProvider(
            endpoint="https://test.openai.azure.com/",
            api_key="dummy_key",
            deployment="gpt-4o",
        )
        result = provider.create_response(
            input_text="你好",
            instructions="你是一个助手",
            enable_web_search=True,
        )

        self.assertEqual(result.text, "你好！我是 Azure Responses API")
        self.assertEqual(result.response_id, "resp_123")
        self.assertEqual(result.usage["total_tokens"], 40)

        mock_client.responses.create.assert_called_once()
        call_kwargs = mock_client.responses.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "gpt-4o")
        self.assertEqual(call_kwargs["input"], "你好")
        self.assertEqual(call_kwargs["instructions"], "你是一个助手")
        self.assertIn({"type": "web_search_preview"}, call_kwargs["tools"])

    @patch("my_openai_robot.responses_api.openai_provider.OpenAI")
    def test_openai_provider_create_response(self, mock_openai_client_cls):
        mock_client = MagicMock()
        mock_openai_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.output_text = "你好！我是 OpenAI 官方 Responses API"
        mock_response.id = "resp_456"
        mock_response.model = "gpt-4o"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 20
        mock_response.usage.total_tokens = 30
        mock_client.responses.create.return_value = mock_response

        provider = OpenAIResponsesProvider(
            api_key="sk-test-key",
            model="gpt-4o",
        )
        result = provider.create_response(input_text="你好")

        self.assertEqual(result.text, "你好！我是 OpenAI 官方 Responses API")
        self.assertEqual(result.response_id, "resp_456")
        self.assertEqual(result.usage["total_tokens"], 30)
        mock_client.responses.create.assert_called_once()

    def test_adapter_bridges_to_chat_protocol(self):
        mock_provider = MagicMock(spec=BaseResponsesProvider)
        mock_provider.create_response.return_value = ResponseResult(
            text="巴黎是法国的首都",
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            model="gpt-4.1-mini",
        )

        adapter = ResponsesAPIClientAdapter(mock_provider, enable_web_search=True)
        messages = [
            Message(role="system", content="你是一个地理专家"),
            Message(role="user", content="法国首都是哪里？"),
        ]
        chat_resp = adapter.chat(messages)

        self.assertEqual(chat_resp.text, "巴黎是法国的首都")
        self.assertEqual(chat_resp.model, "gpt-4.1-mini")
        mock_provider.create_response.assert_called_once_with(
            input_text="法国首都是哪里？",
            instructions="你是一个地理专家",
            enable_web_search=True,
            temperature=1.0,
            max_output_tokens=None,
        )

    def test_adapter_bridges_to_chat_stream(self):
        mock_provider = MagicMock(spec=BaseResponsesProvider)
        mock_provider.create_response_stream.return_value = iter(["巴黎", "是", "法国", "首都。"])

        adapter = ResponsesAPIClientAdapter(mock_provider, enable_web_search=False)
        messages = [
            Message(role="system", content="你是一个地理专家"),
            Message(role="user", content="法国首都是哪里？"),
        ]
        tokens = list(adapter.chat_stream(messages))
        self.assertEqual(tokens, ["巴黎", "是", "法国", "首都。"])
        mock_provider.create_response_stream.assert_called_once_with(
            input_text="法国首都是哪里？",
            instructions="你是一个地理专家",
            enable_web_search=False,
            temperature=1.0,
            max_output_tokens=None,
        )


if __name__ == "__main__":
    unittest.main()
