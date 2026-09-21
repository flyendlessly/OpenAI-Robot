"""Unit tests for the wake word detection system (Sherpa-ONNX offline open-source)."""
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from my_openai_robot.config import WakeWordSettings
from my_openai_robot.wake_word import (
    BUILTIN_KEYWORD_PHONEMES,
    SherpaOnnxWakeWordDetector,
    _convert_chinese_to_kws_lines,
    create_wake_word_detector,
    ensure_sherpa_model,
    list_builtin_keywords,
)


class TestWakeWordModule(unittest.TestCase):
    """测试唤醒词配置、拼音音素生成及工厂模式"""

    def test_settings_defaults(self):
        settings = WakeWordSettings()
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.backend, "sherpa-onnx")
        self.assertIn("你好小智", settings.keywords)
        self.assertEqual(settings.num_threads, 1)
        self.assertEqual(settings.keywords_score, 1.5)
        self.assertEqual(settings.keywords_threshold, 0.25)

    def test_chinese_to_kws_lines_builtin(self):
        # 内置静态表词转换测试
        lines = _convert_chinese_to_kws_lines("你好小智")
        self.assertTrue(len(lines) >= 1)
        self.assertIn("@你好小智", lines[0])

        # 测试芝麻开门包含多音调变体（二声 má 与 轻声 ma）
        zhima_lines = _convert_chinese_to_kws_lines("芝麻开门")
        self.assertTrue(len(zhima_lines) >= 2)
        combined = " ".join(zhima_lines)
        self.assertIn("m á", combined)
        self.assertIn("@芝麻开门", combined)

    def test_chinese_to_kws_lines_dynamic(self):
        # 测试使用 pypinyin 动态转换不在内置表中的新词
        lines = _convert_chinese_to_kws_lines("早安地球")
        self.assertTrue(len(lines) >= 1)
        self.assertIn("@早安地球", lines[0])
        self.assertTrue(any("z" in line or "ao" in line for line in lines))

    def test_factory_disabled_returns_none(self):
        settings = WakeWordSettings(enabled=False)
        detector = create_wake_word_detector(settings)
        self.assertIsNone(detector)

    def test_list_builtin_keywords(self):
        sherpa_kws = list_builtin_keywords()
        self.assertIn("你好小智", sherpa_kws)
        self.assertIn("小爱同学", sherpa_kws)
        self.assertIn("芝麻开门", sherpa_kws)


class TestSherpaOnnxDetectorIntegration(unittest.TestCase):
    """测试 SherpaOnnxWakeWordDetector 与本地 ONNX 模型的接口兼容与执行"""

    @classmethod
    def setUpClass(cls):
        cls.model_dir = Path("data/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01")
        if not cls.model_dir.exists() or not (cls.model_dir / "tokens.txt").exists():
            raise unittest.SkipTest("Sherpa-ONNX 预训练模型目录不存在，跳过模型真实推理测试")

    def test_detector_initialization_and_properties(self):
        settings = WakeWordSettings(
            enabled=True,
            backend="sherpa-onnx",
            model_dir=self.model_dir,
            keywords=["你好小智", "小智小智"],
        )
        detector = create_wake_word_detector(settings)
        self.assertIsNotNone(detector)
        self.assertIsInstance(detector, SherpaOnnxWakeWordDetector)
        self.assertEqual(detector.sample_rate, 16000)
        self.assertEqual(detector.frame_length, 512)

        # 测试静音 PCM 帧输入
        silence_frame = b"\x00" * (detector.frame_length * 2)
        detected, index = detector.process_audio(silence_frame)
        self.assertFalse(detected)
        self.assertEqual(index, -1)

        # 测试 reset 与 context manager 正常退出
        detector.reset()
        detector.close()

    def test_detector_context_manager(self):
        settings = WakeWordSettings(
            enabled=True,
            backend="sherpa-onnx",
            model_dir=self.model_dir,
            keywords=["你好小智"],
        )
        with create_wake_word_detector(settings) as detector:
            self.assertIsNotNone(detector)
            frame = b"\x00" * (detector.frame_length * 2)
            detected, _ = detector.process_audio(frame)
            self.assertFalse(detected)


if __name__ == "__main__":
    unittest.main()
