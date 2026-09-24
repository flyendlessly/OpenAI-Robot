"""CLI entry point and command router."""
from __future__ import annotations

import sys
from typing import Optional

from ..config import AppConfig
from ..context import create_app_context
from ..logger import setup_logging
from .commands.doctor import (
    download_wake_model_command,
    list_devices_command,
    list_wake_words_command,
    test_microphone_command,
)
from .commands.interactive import (
    run_interactive_loop_command,
    run_single_turn_command,
    run_voice_turn_command,
)
from .commands.wake import run_wake_word_command
from .parser import build_arg_parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 主分发入口"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    setup_logging(level=args.log_level, log_file=args.log_file)

    # 1. 优先响应本地硬件与设备调试指令（无需连接云端服务与数据库）
    if args.list_devices:
        return list_devices_command()

    if args.test_microphone:
        return test_microphone_command(device=args.input_device)

    config = AppConfig.from_env()

    if args.download_wake_model:
        return download_wake_model_command(config)

    if args.list_wake_words:
        return list_wake_words_command()

    # 2. 组装运行时 SSOT 上下文 (AppContext)
    ctx = create_app_context(config, args)

    # 3. 命令路由派发
    if args.wake_word:
        return run_wake_word_command(ctx)

    if args.voice_turn:
        return run_voice_turn_command(ctx)

    if args.prompt:
        return run_single_turn_command(ctx, args.prompt)

    return run_interactive_loop_command(ctx)
