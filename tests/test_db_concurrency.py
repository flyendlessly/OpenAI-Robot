"""Harness test for Database Unit of Work, SAVEPOINT nesting, Read-Only, cursor lifecycle, and multi-threaded concurrency."""
import concurrent.futures
import shutil
import tempfile
import unittest
from pathlib import Path

from my_openai_robot.billing_tracker import SQLiteBillingTracker
from my_openai_robot.config import BillingSettings
from my_openai_robot.conversation_store import ConversationStore
from my_openai_robot.db import Database, WriteResult


class TestDatabaseConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_concurrency.db"
        self.db = Database(self.db_path, timeout=5.0)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unit_of_work_commit_and_rollback(self) -> None:
        """测试基础工作单元：正常时自动 commit，异常时自动 rollback"""
        with self.db.unit_of_work() as conn:
            conn.execute(
                "CREATE TABLE test_table (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO test_table (value) VALUES ('hello')")

        # 验证已写入
        row = self.db.fetch_one("SELECT COUNT(*) as cnt FROM test_table")
        self.assertIsNotNone(row)
        self.assertEqual(row["cnt"], 1)

        # 测试异常自动回滚
        with self.assertRaises(ValueError):
            with self.db.unit_of_work() as conn:
                conn.execute("INSERT INTO test_table (value) VALUES ('will_fail')")
                raise ValueError("强制中断事务")

        # 验证未写入被回滚的数据
        row = self.db.fetch_one("SELECT COUNT(*) as cnt FROM test_table")
        self.assertIsNotNone(row)
        self.assertEqual(row["cnt"], 1)

    def test_nested_unit_of_work_with_savepoints(self) -> None:
        """验证 SAVEPOINT 嵌套事务：内层异常回滚不破坏外层事务，且无次生 RELEASE 异常"""
        with self.db.unit_of_work() as conn:
            conn.execute(
                "CREATE TABLE nested_test (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
            )

        # 外层开启事务
        with self.db.unit_of_work() as conn:
            conn.execute("INSERT INTO nested_test (name) VALUES ('outer_1')")

            # 嵌套内层 1：成功完成
            with self.db.unit_of_work() as inner_conn_1:
                inner_conn_1.execute("INSERT INTO nested_test (name) VALUES ('inner_success')")

            # 嵌套内层 2：抛出异常被捕获，应当仅回滚 inner_fail
            try:
                with self.db.unit_of_work() as inner_conn_2:
                    inner_conn_2.execute("INSERT INTO nested_test (name) VALUES ('inner_fail')")
                    raise RuntimeError("内层操作失败")
            except RuntimeError:
                pass  # 外层决定吞掉异常并继续

            conn.execute("INSERT INTO nested_test (name) VALUES ('outer_2')")

        # 验证结果：outer_1, inner_success, outer_2 均成功保留；inner_fail 被精准独立回滚！
        rows = self.db.fetch_all("SELECT name FROM nested_test ORDER BY id")
        names = [r["name"] for r in rows]
        self.assertEqual(names, ["outer_1", "inner_success", "outer_2"])
        self.assertNotIn("inner_fail", names)

    def test_strongly_typed_write_result(self) -> None:
        """验证问题 3：彻底消灭 cursor.lastrowid or cursor.rowcount 的判断歧义"""
        with self.db.unit_of_work() as conn:
            conn.execute(
                "CREATE TABLE item_test (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
            )

        # 1. 验证 INSERT 操作：返回明确的 last_insert_id
        res_insert = self.db.execute_write("INSERT INTO item_test (name) VALUES (?)", ("item1",))
        self.assertIsInstance(res_insert, WriteResult)
        self.assertEqual(res_insert.last_insert_id, 1)
        self.assertEqual(res_insert.rows_affected, 1)

        # 2. 验证 UPDATE 0 行匹配：rows_affected 精确为 0，last_insert_id 精确为 None（绝不被历史值污染）
        res_update_zero = self.db.execute_write(
            "UPDATE item_test SET name = ? WHERE id = 999", ("non_existent",)
        )
        self.assertEqual(res_update_zero.rows_affected, 0)
        self.assertIsNone(res_update_zero.last_insert_id)

        # 3. 验证 UPDATE 1 行匹配
        res_update_one = self.db.execute_write(
            "UPDATE item_test SET name = ? WHERE id = 1", ("updated_item",)
        )
        self.assertEqual(res_update_one.rows_affected, 1)
        self.assertIsNone(res_update_one.last_insert_id)

    def test_ryow_nested_read_only_in_unit_of_work(self) -> None:
        """验证问题 8：写事务内嵌套 read_only，能天然支持 RYOW (Read Your Own Writes) 且不额外开启事务"""
        with self.db.unit_of_work() as conn:
            conn.execute("CREATE TABLE ryow_test (id INTEGER PRIMARY KEY, msg TEXT NOT NULL)")

        # 在写事务未提交前
        with self.db.unit_of_work() as conn:
            conn.execute("INSERT INTO ryow_test (id, msg) VALUES (1, 'uncommitted_write')")

            # 嵌套 read_only 查询自身未提交的数据
            row = self.db.fetch_one("SELECT msg FROM ryow_test WHERE id = 1")
            self.assertIsNotNone(row)
            self.assertEqual(row["msg"], "uncommitted_write")

        # 退出写事务后已成功提交
        final_row = self.db.fetch_one("SELECT msg FROM ryow_test WHERE id = 1")
        self.assertEqual(final_row["msg"], "uncommitted_write")

    def test_materialized_queries_and_writes(self) -> None:
        """验证 fetch_one / fetch_all 在事务退出后数据依然物化可用，不暴露脱轨游标"""
        with self.db.unit_of_work() as conn:
            conn.execute(
                "CREATE TABLE mat_test (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
            )

        # 测试批量写入与返回行数
        count = self.db.execute_batch(
            "INSERT INTO mat_test (id, title) VALUES (?, ?)",
            [(1, "A"), (2, "B"), (3, "C")],
        )
        self.assertEqual(count, 3)

        # 单行物化读取
        row = self.db.fetch_one("SELECT * FROM mat_test WHERE id = ?", (2,))
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "B")

        # 多行物化读取
        all_rows = self.db.fetch_all("SELECT * FROM mat_test ORDER BY id")
        self.assertEqual(len(all_rows), 3)
        self.assertEqual([r["title"] for r in all_rows], ["A", "B", "C"])

    def test_close_and_reopen_connection(self) -> None:
        """验证问题 7：显式关闭连接前主动回滚残留事务并释放文件句柄，且重新操作能够安全自愈新建连接"""
        row = self.db.fetch_one("SELECT 1 as num")
        self.assertEqual(row["num"], 1)

        # 显式关闭
        self.db.close()
        self.assertIsNone(getattr(self.db._local, "conn", None))

        # 再次操作自动重连
        row2 = self.db.fetch_one("SELECT 2 as num")
        self.assertEqual(row2["num"], 2)
        self.assertIsNotNone(getattr(self.db._local, "conn", None))

    def test_multi_threaded_concurrent_reads_and_writes(self) -> None:
        """验证测试多线程并发写入与聚合读取，验证 BEGIN IMMEDIATE + WAL + busy_timeout 下绝无死锁或锁库"""
        store = ConversationStore(self.db)
        settings = BillingSettings(storage_path=self.db_path)
        tracker = SQLiteBillingTracker(settings, db=self.db)

        write_iterations_per_thread = 20
        read_iterations_per_thread = 20
        num_writers = 4
        num_readers = 4

        errors: list[Exception] = []

        def writer_task(thread_id: int) -> None:
            try:
                for i in range(write_iterations_per_thread):
                    store.log(
                        user_input=f"thread-{thread_id}-query-{i}",
                        assistant_response=f"thread-{thread_id}-reply-{i}",
                        model="gpt-test",
                        usage_tokens=100,
                    )
                    tracker.record_usage({
                        "prompt_tokens": 50,
                        "completion_tokens": 50,
                        "stt_duration_seconds": 1.0,
                    })
            except Exception as e:
                errors.append(e)

        def reader_task(thread_id: int) -> None:
            try:
                for _ in range(read_iterations_per_thread):
                    cost = tracker.get_monthly_cost()
                    self.assertGreaterEqual(cost, 0.0)
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=num_writers + num_readers
        ) as executor:
            futures = []
            for w in range(num_writers):
                futures.append(executor.submit(writer_task, w))
            for r in range(num_readers):
                futures.append(executor.submit(reader_task, r))

            concurrent.futures.wait(futures)

        # 断言在交叉并发下 0 异常，0 锁库死锁报错
        self.assertEqual(errors, [])

        # 验证写入的数据总量精确匹配
        total_writes = num_writers * write_iterations_per_thread
        logs_count = self.db.fetch_one("SELECT COUNT(*) as cnt FROM conversation_logs")["cnt"]
        usage_count = self.db.fetch_one("SELECT COUNT(*) as cnt FROM usage_records")["cnt"]
        self.assertEqual(logs_count, total_writes)
        self.assertEqual(usage_count, total_writes)


if __name__ == "__main__":
    unittest.main()
