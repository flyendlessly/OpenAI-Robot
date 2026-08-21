"""Conversation log storage - 对话记录持久化到 SQLite"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .logger import get_logger

logger = get_logger("conversation_store")


class ConversationStore:
    """将对话问答存储到 SQLite conversation_logs 表"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保表存在（兼容迁移未运行的情况）"""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    model TEXT,
                    mode TEXT,
                    usage_tokens INTEGER DEFAULT 0,
                    duration_ms INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_logs_timestamp ON conversation_logs(timestamp)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def log(
        self,
        user_input: str,
        assistant_response: str,
        *,
        model: Optional[str] = None,
        mode: str = "text",
        usage_tokens: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """记录一次对话

        Args:
            user_input: 用户输入文本
            assistant_response: AI 回复文本
            model: 模型部署名称
            mode: 对话模式 (text/voice/wake_word)
            usage_tokens: 总 token 数
            duration_ms: 请求耗时（毫秒）
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_logs
                    (timestamp, user_input, assistant_response, model, mode, usage_tokens, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, user_input, assistant_response, model, mode, usage_tokens, duration_ms),
            )
        logger.debug("对话已记录: user=%s..., model=%s", user_input[:20], model)
