"""CLI diagnostic and setup commands."""
from __future__ import annotations

from typing import Optional

from ...audio_io import list_audio_devices, test_microphone
from ...config import AppConfig
from ...wake_word import ensure_sherpa_model, list_builtin_keywords


def list_devices_command() -> int:
    """列出所有音频设备"""
    list_audio_devices()
    return 0


def test_microphone_command(device: Optional[int] = None) -> int:
    """测试指定或默认麦克风"""
    test_microphone(device=device)
    return 0


def download_wake_model_command(config: AppConfig) -> int:
    """检查并下载 Sherpa-ONNX 预训练离线中文唤醒词模型"""
    print("\n正在检查/下载 Sherpa-ONNX 预训练离线中文唤醒词模型...")
    target_dir = ensure_sherpa_model(config.wake_word.model_dir, auto_download=True)
    print(f"[OK] 唤醒词模型已就绪: {target_dir}\n")
    return 0


def list_wake_words_command() -> int:
    """列出支持的内置唤醒词"""
    print("\n支持的内置/推荐中文唤醒词 (Sherpa-ONNX 离线开源):")
    print("=" * 50)
    for keyword in list_builtin_keywords():
        print(f"  * {keyword}")
    print("\n使用方法:")
    print("  在 .env 中设置: WAKE_WORD_KEYWORDS=芝麻开门,你好小智,小智小智 (支持自定义任意中文词，无需从零训练)")
    print("  启动唤醒词监听模式: python -m my_openai_robot --wake-word --use-vad\n")
    return 0
