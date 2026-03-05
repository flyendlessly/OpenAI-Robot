"""初始化数据库表结构

创建 usage_records 表的初始版本
"""

NAME = "初始化 usage_records 表"


def up(conn):
    """创建初始表结构"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL
        )
        """
    )


def down(conn):
    """回滚：删除表"""
    conn.execute("DROP TABLE IF EXISTS usage_records")
