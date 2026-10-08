"""Robust Database Infrastructure with explicit snapshot reads, SAVEPOINT nesting, retry backoff, and strongly-typed WriteResult."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple, Union

from .logger import get_logger

logger = get_logger("db")


@dataclass
class WriteResult:
    """写操作明确的返回结果（消灭 lastrowid or rowcount 歧义 bug）"""

    last_insert_id: Optional[int] = None
    rows_affected: int = 0


class Database:
    """统一 SQLite 基础设施：
    1. 线程安全隔离：基于 Thread-Local 保证线程私有连接；
    2. 防死锁设计：顶层写事务采用 BEGIN IMMEDIATE 独占写锁；
    3. 嵌套事务支持：内层事务基于 SAVEPOINT，内层异常只回滚当前保存点，不破坏外层；
    4. 读事务隔离与防 WAL 挂起：只读模式采用 BEGIN DEFERRED并在退出时显式释放快照；
    5. 支持 RYOW (Read-Your-Own-Writes)：写事务内嵌套只读查询自动复用同一写上下文；
    6. 安全类型返回：提供 fetch_one / fetch_all 数据物化，写入返回 WriteResult；
    7. 弹性重试：遇到瞬态 SQLITE_BUSY 自动执行指数退避重试。
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        timeout: float = 10.0,
        max_busy_retries: int = 3,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout = timeout
        self.max_busy_retries = max_busy_retries
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程独享的连接，启用 autocommit (isolation_level=None) 精准接管事务边界"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.timeout,
                isolation_level=None,  # 禁用标准库隐式事务，显式管控 BEGIN/COMMIT
                check_same_thread=True,
            )
            conn.row_factory = sqlite3.Row

            # 1. 开启 WAL (Write-Ahead Logging) 模式
            conn.execute("PRAGMA journal_mode=WAL;")
            # 2. 开启忙等超时 (5000ms)
            conn.execute("PRAGMA busy_timeout=5000;")
            # 3. 针对树莓派 SD 卡减少阻塞式 fsync
            conn.execute("PRAGMA synchronous=NORMAL;")
            # 4. 开启外键约束支持
            conn.execute("PRAGMA foreign_keys=ON;")

            self._local.conn = conn
            self._local.depth = 0
            self._local.in_read = False
            logger.debug("为线程 %s 创建并初始化新数据库连接: %s", threading.get_ident(), self.db_path)
        return conn

    @contextmanager
    def unit_of_work(self) -> Iterator[sqlite3.Connection]:
        """写事务工作单元：
        - 外层（depth=1）：执行 BEGIN IMMEDIATE 抢占写锁，预防死锁；
        - 内层（depth>1）：执行 SAVEPOINT sp_{depth}，支持嵌套；
        - 异常退出时：仅执行 ROLLBACK / ROLLBACK TO SAVEPOINT，不重复执行 RELEASE 消除次生异常；
        - 遭遇瞬态 SQLITE_BUSY 时自动进行指数退避重试。
        """
        conn = self._get_connection()

        # 嵌套在已有事务内时，直接走 SAVEPOINT，不重新触发顶层重试
        if getattr(self._local, "depth", 0) > 0:
            self._local.depth += 1
            current_depth = self._local.depth
            savepoint_name = f"sp_{current_depth}"
            conn.execute(f"SAVEPOINT {savepoint_name};")
            try:
                yield conn
                conn.execute(f"RELEASE SAVEPOINT {savepoint_name};")
            except Exception as exc:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name};")
                except Exception:
                    pass
                logger.debug("内层 SAVEPOINT (depth=%d) 回滚: %s", current_depth, exc)
                raise
            finally:
                self._local.depth -= 1
            return

        # 顶层写事务（支持 BUSY 重试）
        retries = 0
        while True:
            try:
                self._local.depth = 1
                conn.execute("BEGIN IMMEDIATE;")
                try:
                    yield conn
                    conn.execute("COMMIT;")
                    return
                except Exception as exc:
                    try:
                        conn.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise exc
                finally:
                    self._local.depth = 0
            except sqlite3.OperationalError as op_err:
                self._local.depth = 0
                if "locked" in str(op_err).lower() or "busy" in str(op_err).lower():
                    retries += 1
                    if retries <= self.max_busy_retries:
                        sleep_time = 0.05 * (2 ** (retries - 1))
                        logger.warning("遇到数据库忙/锁定错误，正在进行第 %d 次重试 (等待 %.2fs)...", retries, sleep_time)
                        time.sleep(sleep_time)
                        continue
                raise

    @contextmanager
    def read_only(self) -> Iterator[sqlite3.Connection]:
        """只读事务工作单元：
        - 若当前已处于写事务中：直接复用写连接上下文（支持 RYOW 读自己未提交写入），不新建读事务；
        - 若当前未在事务中：显式执行 BEGIN DEFERRED 提供一致性可重复读快照，并在退出时执行 ROLLBACK 及时释放快照与锁，杜绝 WAL 挂起。
        """
        conn = self._get_connection()
        already_in_tx = getattr(self._local, "depth", 0) > 0 or getattr(self._local, "in_read", False)

        if already_in_tx:
            # 继承已有事务上下文
            yield conn
            return

        self._local.in_read = True
        try:
            conn.execute("BEGIN DEFERRED;")
            yield conn
        finally:
            try:
                conn.execute("ROLLBACK;")  # 释放读快照，消除对 WAL Checkpoint 的长期占用
            except Exception:
                pass
            self._local.in_read = False

    def fetch_one(
        self, sql: str, parameters: Tuple[Any, ...] = ()
    ) -> Optional[sqlite3.Row]:
        """安全读取单行：数据在上下文内完成物化后再返回，无游标逃逸"""
        with self.read_only() as conn:
            cursor = conn.execute(sql, parameters)
            return cursor.fetchone()

    def fetch_all(
        self, sql: str, parameters: Tuple[Any, ...] = ()
    ) -> List[sqlite3.Row]:
        """安全读取多行：数据在上下文内完成物化后再返回，无游标逃逸"""
        with self.read_only() as conn:
            cursor = conn.execute(sql, parameters)
            return cursor.fetchall()

    def execute_write(
        self, sql: str, parameters: Tuple[Any, ...] = ()
    ) -> WriteResult:
        """执行单次写操作，返回强类型的 WriteResult，彻底消除 lastrowid or rowcount 歧义"""
        with self.unit_of_work() as conn:
            cursor = conn.execute(sql, parameters)
            is_insert = sql.strip().upper().startswith("INSERT")
            last_id = cursor.lastrowid if is_insert and cursor.lastrowid != 0 else None
            return WriteResult(
                last_insert_id=last_id,
                rows_affected=cursor.rowcount if cursor.rowcount != -1 else 0,
            )

    def execute_batch(
        self, sql: str, seq_of_parameters: List[Tuple[Any, ...]]
    ) -> int:
        """批量执行写操作，返回受影响行数"""
        with self.unit_of_work() as conn:
            cursor = conn.executemany(sql, seq_of_parameters)
            return cursor.rowcount

    def close(self) -> None:
        """显式关闭当前线程独享的连接，主动回滚残留事务并释放文件句柄"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None
            self._local.depth = 0
            self._local.in_read = False
