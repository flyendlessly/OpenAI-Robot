"""Conversation log storage - 对话记录持久化到 SQLite"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from .db import Database
from .logger import get_logger

logger = get_logger("conversation_store")


class ConversationStore:
    """将对话问答存储到 SQLite conversation_logs 表（基于 Database Unit of Work）"""

    def __init__(self, db: Union[Database, Path, str]) -> None:
        if isinstance(db, Database):
            self.db = db
        else:
            self.db = Database(db)
        self.db_path = self.db.db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保表存在（兼容迁移未运行的情况）"""
        with self.db.unit_of_work() as conn:
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
        """记录一次对话（在独立的 Unit of Work 事务中提交）"""
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        with self.db.unit_of_work() as conn:
            conn.execute(
                """
                INSERT INTO conversation_logs
                    (timestamp, user_input, assistant_response, model, mode, usage_tokens, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, user_input, assistant_response, model, mode, usage_tokens, duration_ms),
            )
        logger.debug("对话已记录: user=%s..., model=%s", user_input[:20], model)
