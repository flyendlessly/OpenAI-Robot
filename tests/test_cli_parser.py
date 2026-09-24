"""Tests for CLI argument parser."""
import unittest

from my_openai_robot.cli.parser import build_arg_parser


class TestCLIParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_arg_parser()

    def test_default_arguments(self) -> None:
        args = self.parser.parse_args([])
        self.assertIsNone(args.prompt)
        self.assertEqual(args.system_prompt, "你是一个乐于助人的中文语音助手。")
        self.assertEqual(args.max_tokens, 512)
        self.assertEqual(args.temperature, 1.0)
        self.assertTrue(args.stream)
        self.assertFalse(args.voice_turn)
        self.assertFalse(args.wake_word)
        self.assertFalse(args.list_devices)
        self.assertEqual(args.vad_aggressiveness, 2)
        self.assertIsNone(args.web_search)

    def test_override_flags(self) -> None:
        args = self.parser.parse_args([
            "你好世界",
            "--no-stream",
            "--wake-word",
            "--provider", "openai",
            "--web-search",
            "--record-seconds", "8.0",
        ])
        self.assertEqual(args.prompt, "你好世界")
        self.assertFalse(args.stream)
        self.assertTrue(args.wake_word)
        self.assertEqual(args.provider, "openai")
        self.assertTrue(args.web_search)
        self.assertEqual(args.record_seconds, 8.0)

    def test_diagnostic_flags(self) -> None:
        args = self.parser.parse_args(["--list-devices", "--test-microphone", "--list-wake-words"])
        self.assertTrue(args.list_devices)
        self.assertTrue(args.test_microphone)
        self.assertTrue(args.list_wake_words)


if __name__ == "__main__":
    unittest.main()
