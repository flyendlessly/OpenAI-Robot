"""创建 conversation_logs 表

记录每次对话的问答内容、模型版本和时间
"""

NAME = "创建 conversation_logs 对话记录表"


def up(conn):
    """创建对话记录表"""
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
    # 按时间查询的索引
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_logs_timestamp ON conversation_logs(timestamp)"
    )


def down(conn):
    """回滚：删除表"""
    conn.execute("DROP TABLE IF EXISTS conversation_logs")
