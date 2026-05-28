"""Logging configuration for the voice assistant."""
# 统一日志模块：支持控制台彩色输出 + 文件输出，按模块名区分
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str | Path] = None,
    *,
    console: bool = True,
) -> None:
    """初始化全局日志配置（只执行一次）

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 可选，日志文件路径（追加模式）
        console: 是否输出到控制台
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    root_logger = logging.getLogger("my_openai_robot")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """获取子模块 logger，自动带 'my_openai_robot.' 前缀"""
    return logging.getLogger(f"my_openai_robot.{name}")
