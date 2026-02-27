"""Track Azure OpenAI usage and estimated cost."""
# 费用追踪模块：解析 Azure usage 并持久化，便于额度管理
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Protocol

from .config import BillingSettings


@dataclass
class UsageRecord:
    """一次调用的 token 数与估算成本"""

    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class BillingTrackerProtocol(Protocol):
    """计费追踪插件约定接口"""

    settings: BillingSettings

    def record_usage(self, usage: Dict[str, Any]) -> UsageRecord:
        ...

    def get_monthly_cost(self) -> float:
        ...

    def should_warn(self, monthly_cost: float | None = None) -> bool:
        ...


class SQLiteBillingTracker(BillingTrackerProtocol):
    """默认 SQLite 实现，用于离线记录"""

    def __init__(self, settings: BillingSettings) -> None:
        self.settings = settings
        self.db_path = settings.storage_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        prompt_cost = (prompt_tokens / 1000) * self.settings.prompt_cost_per_1k
        completion_cost = (completion_tokens / 1000) * self.settings.completion_cost_per_1k
        return round(prompt_cost + completion_cost, 6)

    def record_usage(self, usage: Dict[str, Any]) -> UsageRecord:
        """根据 Azure 返回的 usage 计算费用，并写入存储"""
        prompt_tokens = self._coerce_int(
            usage.get("prompt_tokens") or usage.get("input_tokens")
        )
        completion_tokens = self._coerce_int(
            usage.get("completion_tokens") or usage.get("output_tokens")
        )
        cost_usd = self._estimate_cost(prompt_tokens, completion_tokens)
        record = UsageRecord(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_records (timestamp, prompt_tokens, completion_tokens, cost_usd)
                VALUES (?, ?, ?, ?)
                """,
                (timestamp, record.prompt_tokens, record.completion_tokens, record.cost_usd),
            )
        return record

    def get_monthly_cost(self) -> float:
        """统计本月（UTC）累计费用"""
        now = datetime.now(tz=timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_records WHERE timestamp >= ?",
                (month_start.isoformat(),),
            )
            total = cursor.fetchone()[0]
        return float(total or 0.0)

    def should_warn(self, monthly_cost: float | None = None) -> bool:
        """判断是否达到告警阈值"""
        if monthly_cost is None:
            monthly_cost = self.get_monthly_cost()
        threshold = self.settings.monthly_budget_usd * self.settings.warn_ratio
        return monthly_cost >= threshold


TrackerFactory = Callable[[BillingSettings], BillingTrackerProtocol]


TRACKER_FACTORIES: Dict[str, TrackerFactory] = {
    "sqlite": SQLiteBillingTracker,
}


def register_billing_provider(name: str, factory: TrackerFactory) -> None:
    """允许在运行时注册新的计费插件"""
    TRACKER_FACTORIES[name.lower()] = factory


def create_billing_tracker(settings: BillingSettings) -> Optional[BillingTrackerProtocol]:
    """根据配置创建计费插件，不存在则返回 None"""
    provider = (settings.provider or "").lower()
    factory = TRACKER_FACTORIES.get(provider)
    if not factory:
        return None
    return factory(settings)
