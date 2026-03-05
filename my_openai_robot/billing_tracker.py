"""Track Azure OpenAI usage and estimated cost."""
# 费用追踪模块：解析 Azure usage 并持久化，便于额度管理
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Protocol

from .config import BillingSettings


@dataclass
class UsageRecord:
    """一次调用的使用量与估算成本"""

    # LLM 使用量
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Speech 使用量
    stt_duration_seconds: float = 0.0  # STT 音频时长（秒）
    tts_characters: int = 0  # TTS 字符数
    # 总成本
    cost_usd: float = 0.0
    # 成本细分
    llm_cost: float = 0.0
    stt_cost: float = 0.0
    tts_cost: float = 0.0


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
        self._run_migrations()

    def _run_migrations(self) -> None:
        """使用迁移系统初始化/更新数据库"""
        migrations_dir = Path(__file__).parent.parent / "migrations"
        
        # 动态导入避免循环依赖
        sys.path.insert(0, str(migrations_dir.parent))
        from migrations.migration_runner import MigrationRunner
        
        runner = MigrationRunner(self.db_path, migrations_dir)
        pending = runner.get_pending_migrations()
        
        if pending:
            # 静默执行待应用的迁移
            for migration in pending:
                with self._connect() as conn:
                    migration.up(conn)
                    conn.execute(
                        "INSERT OR IGNORE INTO __migration_history (version, name, applied_at) VALUES (?, ?, ?)",
                        (migration.version, migration.name, datetime.utcnow().isoformat()),
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

    def _estimate_llm_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """计算 LLM token 成本"""
        prompt_cost = (prompt_tokens / 1000) * self.settings.prompt_cost_per_1k
        completion_cost = (completion_tokens / 1000) * self.settings.completion_cost_per_1k
        return round(prompt_cost + completion_cost, 6)
    
    def _estimate_stt_cost(self, duration_seconds: float) -> float:
        """计算 STT 成本（按小时）"""
        hours = duration_seconds / 3600
        return round(hours * self.settings.stt_cost_per_hour, 6)
    
    def _estimate_tts_cost(self, characters: int) -> float:
        """计算 TTS 成本（按百万字符）"""
        millions = characters / 1_000_000
        return round(millions * self.settings.tts_cost_per_million_chars, 6)

    def record_usage(self, usage: Dict[str, Any]) -> UsageRecord:
        """根据 Azure 返回的 usage 计算费用，并写入存储
        
        支持的字段：
        - prompt_tokens / input_tokens: LLM 输入 token
        - completion_tokens / output_tokens: LLM 输出 token
        - stt_duration_seconds: STT 音频时长（秒）
        - tts_characters: TTS 字符数
        """
        # LLM token
        prompt_tokens = self._coerce_int(
            usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        )
        completion_tokens = self._coerce_int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
        
        # Speech 使用量
        stt_duration = float(usage.get("stt_duration_seconds", 0.0))
        tts_chars = self._coerce_int(usage.get("tts_characters", 0))
        
        # 计算各项成本
        llm_cost = self._estimate_llm_cost(prompt_tokens, completion_tokens)
        stt_cost = self._estimate_stt_cost(stt_duration)
        tts_cost = self._estimate_tts_cost(tts_chars)
        total_cost = llm_cost + stt_cost + tts_cost
        
        record = UsageRecord(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            stt_duration_seconds=stt_duration,
            tts_characters=tts_chars,
            cost_usd=total_cost,
            llm_cost=llm_cost,
            stt_cost=stt_cost,
            tts_cost=tts_cost,
        )
        
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_records (
                    timestamp, prompt_tokens, completion_tokens,
                    stt_duration_seconds, tts_characters,
                    cost_usd, llm_cost, stt_cost, tts_cost
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.stt_duration_seconds,
                    record.tts_characters,
                    record.cost_usd,
                    record.llm_cost,
                    record.stt_cost,
                    record.tts_cost,
                ),
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
