"""Tests for AppContext and runtime state container."""
import argparse
import unittest
from unittest.mock import MagicMock, patch

from my_openai_robot.config import AppConfig
from my_openai_robot.context import AppContext, create_app_context
from my_openai_robot.llm_client import LLMResponse


class TestAppContext(unittest.TestCase):
    def test_log_usage_and_turn(self) -> None:
        mock_config = MagicMock(spec=AppConfig)
        mock_args = MagicMock(spec=argparse.Namespace)
        mock_client = MagicMock()
        mock_tracker = MagicMock()
        mock_record = MagicMock()
        mock_record.cost_usd = 0.000123
        mock_tracker.record_usage.return_value = mock_record
        mock_tracker.get_monthly_cost.return_value = 0.1234
        mock_tracker.settings.monthly_budget_usd = 10.0
        mock_tracker.should_warn.return_value = False
        mock_store = MagicMock()

        ctx = AppContext(
            config=mock_config,
            args=mock_args,
            llm_client=mock_client,
            billing_tracker=mock_tracker,
            conversation_store=mock_store,
        )

        response = LLMResponse(
            text="测试回复",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            model="gpt-test",
            searched=True,
            search_queries=["天气"],
        )

        ctx.log_usage(response, stt_duration=1.5, tts_characters=4)
        mock_tracker.record_usage.assert_called_once()
        recorded_data = mock_tracker.record_usage.call_args[0][0]
        self.assertEqual(recorded_data["total_tokens"], 30)
        self.assertEqual(recorded_data["stt_duration_seconds"], 1.5)
        self.assertEqual(recorded_data["tts_characters"], 4)

        ctx.log_turn(
            user_input="你好",
            assistant_response="你好！",
            model="gpt-test",
            mode="text",
            usage_tokens=30,
        )
        mock_store.log.assert_called_once_with(
            user_input="你好",
            assistant_response="你好！",
            model="gpt-test",
            mode="text",
            usage_tokens=30,
        )

    @patch("my_openai_robot.context.create_speech_service")
    @patch("my_openai_robot.context.ResponsesAPIClientAdapter")
    @patch("my_openai_robot.context.get_responses_provider")
    def test_create_app_context_builder(
        self, mock_get_provider: MagicMock, mock_adapter: MagicMock, mock_speech: MagicMock
    ) -> None:
        config = AppConfig.from_env()
        config.billing.enabled = False
        args = argparse.Namespace(
            prompt="测试",
            system_prompt="系统提示",
            max_tokens=100,
            temperature=0.7,
            stream=True,
            voice_turn=False,
            wake_word=False,
            web_search=None,
            search_provider=None,
            provider="azure",
            input_device=None,
            output_device=None,
        )

        ctx = create_app_context(config, args)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.config, config)
        self.assertIsNone(ctx.microphone)
        self.assertIsNone(ctx.speaker)


if __name__ == "__main__":
    unittest.main()
