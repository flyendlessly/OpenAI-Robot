"""Tests for CLI command execution and dispatching."""
import argparse
import unittest
from unittest.mock import MagicMock, patch

from my_openai_robot.cli import main
from my_openai_robot.cli.commands.doctor import (
    list_devices_command,
    list_wake_words_command,
    test_microphone_command,
)
from my_openai_robot.cli.commands.interactive import (
    run_interactive_loop_command,
    run_single_turn_command,
)
from my_openai_robot.context import AppContext
from my_openai_robot.llm_client import LLMResponse


class TestCLICommands(unittest.TestCase):
    @patch("my_openai_robot.cli.commands.doctor.list_audio_devices")
    def test_list_devices_command(self, mock_list_devices: MagicMock) -> None:
        ret = list_devices_command()
        self.assertEqual(ret, 0)
        mock_list_devices.assert_called_once()

    @patch("my_openai_robot.cli.commands.doctor.test_microphone")
    def test_test_microphone_command(self, mock_test_mic: MagicMock) -> None:
        ret = test_microphone_command(device=2)
        self.assertEqual(ret, 0)
        mock_test_mic.assert_called_once_with(device=2)

    @patch("my_openai_robot.cli.commands.doctor.list_builtin_keywords", return_value=["芝麻开门"])
    def test_list_wake_words_command(self, mock_list_kw: MagicMock) -> None:
        ret = list_wake_words_command()
        self.assertEqual(ret, 0)
        mock_list_kw.assert_called_once()

    def test_run_single_turn_command(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.return_value = LLMResponse(
            text="你好！我是助手。",
            usage={"total_tokens": 10},
            model="gpt-test",
        )
        mock_args = argparse.Namespace(
            system_prompt="系统提示",
            max_tokens=100,
            temperature=0.7,
            stream=False,
        )
        mock_store = MagicMock()
        mock_tracker = MagicMock()
        mock_record = MagicMock()
        mock_record.cost_usd = 0.000123
        mock_tracker.record_usage.return_value = mock_record
        mock_tracker.get_monthly_cost.return_value = 0.1234
        mock_tracker.settings.monthly_budget_usd = 10.0
        mock_tracker.should_warn.return_value = False

        ctx = AppContext(
            config=MagicMock(),
            args=mock_args,
            llm_client=mock_client,
            conversation_store=mock_store,
            billing_tracker=mock_tracker,
        )

        ret = run_single_turn_command(ctx, "你好")
        self.assertEqual(ret, 0)
        mock_client.chat.assert_called_once()
        mock_store.log.assert_called_once()

    @patch("my_openai_robot.cli.commands.doctor.list_audio_devices")
    def test_main_dispatch_list_devices(self, mock_list: MagicMock) -> None:
        code = main(["--list-devices"])
        self.assertEqual(code, 0)
        mock_list.assert_called_once()


if __name__ == "__main__":
    unittest.main()
