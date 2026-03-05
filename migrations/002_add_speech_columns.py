"""添加语音服务相关列

为 usage_records 表添加 STT/TTS 使用量和成本细分字段
"""

NAME = "添加语音服务和成本细分列"


def up(conn):
    """添加语音相关列"""
    # 获取现有列
    cursor = conn.execute("PRAGMA table_info(usage_records)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    # 要添加的列及其定义
    columns_to_add = {
        "stt_duration_seconds": "REAL NOT NULL DEFAULT 0",
        "tts_characters": "INTEGER NOT NULL DEFAULT 0",
        "llm_cost": "REAL NOT NULL DEFAULT 0",
        "stt_cost": "REAL NOT NULL DEFAULT 0",
        "tts_cost": "REAL NOT NULL DEFAULT 0",
    }
    
    # 只添加不存在的列
    for col_name, col_def in columns_to_add.items():
        if col_name not in existing_columns:
            conn.execute(f"ALTER TABLE usage_records ADD COLUMN {col_name} {col_def}")
            print(f"  ✅ 添加列: {col_name}")


def down(conn):
    """回滚：SQLite 不支持直接删除列，需要重建表"""
    # 保存旧数据
    conn.execute(
        """
        CREATE TABLE usage_records_backup AS 
        SELECT id, timestamp, prompt_tokens, completion_tokens, cost_usd
        FROM usage_records
        """
    )
    
    # 删除旧表
    conn.execute("DROP TABLE usage_records")
    
    # 创建新表（不含语音列）
    conn.execute(
        """
        CREATE TABLE usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL
        )
        """
    )
    
    # 恢复数据
    conn.execute(
        """
        INSERT INTO usage_records (id, timestamp, prompt_tokens, completion_tokens, cost_usd)
        SELECT id, timestamp, prompt_tokens, completion_tokens, cost_usd
        FROM usage_records_backup
        """
    )
    
    # 删除备份表
    conn.execute("DROP TABLE usage_records_backup")
