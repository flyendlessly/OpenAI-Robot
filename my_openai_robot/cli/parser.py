"""CLI argument parser definition."""
from __future__ import annotations

import argparse


def build_arg_parser() -> argparse.ArgumentParser:
    """提供命令行参数解析器"""
    parser = argparse.ArgumentParser(description="Azure OpenAI 语音助手 CLI")
    parser.add_argument("prompt", nargs="?", help="要发送的用户提示；为空则进入交互模式")
    parser.add_argument("--system", default="你是一个乐于助人的中文语音助手。", dest="system_prompt")
    parser.add_argument("--max-tokens", type=int, default=512, dest="max_tokens")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--voice-turn", action="store_true", help="使用麦克风录制一次语音并播放回复")
    parser.add_argument("--record-seconds", type=float, default=5.0, help="单次语音录制时长（秒），使用 VAD 时为最大时长")
    parser.add_argument("--use-vad", action="store_true", help="使用 VAD 自动检测说话开始和结束（推荐）")
    parser.add_argument("--vad-silence", type=float, default=2.0, help="VAD 模式：连续静音多久后停止（秒）")
    parser.add_argument(
        "--vad-aggressiveness",
        type=int,
        default=2,
        choices=[0, 1, 2, 3],
        help="VAD 灵敏度 0-3，越高越不容易误触发",
    )
    parser.add_argument("--save-reply-audio", help="将 AI 回复语音保存为 WAV 文件")
    parser.add_argument(
        "--stream",
        action="store_true",
        default=True,
        help="启用流式并发流水线（大幅降低语音与文本延迟，默认开启）",
    )
    parser.add_argument("--no-stream", action="store_false", dest="stream", help="禁用流式，使用传统串行模式")
    parser.add_argument("--list-devices", action="store_true", help="列出所有可用音频设备")
    parser.add_argument("--test-microphone", action="store_true", help="测试麦克风是否正常工作")
    parser.add_argument("--input-device", type=int, help="指定输入设备 ID（使用 --list-devices 查看）")
    parser.add_argument("--output-device", type=int, help="指定输出设备 ID（使用 --list-devices 查看）")
    parser.add_argument(
        "--wake-word",
        action="store_true",
        help="启用唤醒词监听模式（持续监听，检测到唤醒词后开始对话）",
    )
    parser.add_argument("--list-wake-words", action="store_true", help="列出所有支持的内置/推荐唤醒词")
    parser.add_argument(
        "--download-wake-model",
        action="store_true",
        help="一键下载并准备 Sherpa-ONNX 预训练离线唤醒词模型",
    )
    parser.add_argument("--web-search", action="store_true", default=None, help="启用联网搜索 (覆盖 .env)")
    parser.add_argument(
        "--no-web-search", action="store_false", dest="web_search", help="禁用联网搜索 (覆盖 .env)"
    )
    parser.add_argument(
        "--provider",
        choices=["azure", "openai", "azure_chat"],
        help="指定 LLM Provider (覆盖 .env 中的 RESPONSES_PROVIDER)",
    )
    parser.add_argument(
        "--search-provider",
        choices=["duckduckgo", "tavily", "bing"],
        help="指定联网搜索引擎",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument("--log-file", help="日志输出文件路径（可选）")
    return parser
