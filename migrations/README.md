# 数据库迁移系统

类似 Entity Framework Migrations 的数据库版本管理工具。

## 🏗️ 架构设计

本系统采用**关注点分离**原则：

- **迁移系统**（`migrations/`）：负责数据库结构（DDL）的版本管理
- **业务代码**（`billing_tracker.py`）：负责数据操作（DML）和业务逻辑

所有数据库表结构的创建和修改都通过迁移脚本管理，应用代码不包含任何 `CREATE TABLE` 或 `ALTER TABLE` 语句。

## 📋 功能特性

- ✅ 自动跟踪已执行的迁移（存储在 `__migration_history` 表）
- ✅ 按版本号顺序执行迁移
- ✅ 支持回滚操作（如果实现了 `down()` 函数）
- ✅ 查看迁移状态
- ✅ 快速创建新迁移脚本

## 🚀 快速开始

### 查看迁移状态

```bash
python migrations/migrate.py status
```

输出示例：
```
📊 数据库迁移状态:

版本                      状态       名称
------------------------------------------------------------
001_init                 ✅ 已应用   初始化 usage_records 表
002_add_speech_columns   ⏸️  待执行   添加语音服务和成本细分列

总计: 2 个迁移，1 个已应用，1 个待执行
```

### 执行迁移

```bash
# 执行所有待执行的迁移
python migrations/migrate.py migrate

# 迁移到指定版本
python migrations/migrate.py migrate 002_add_speech_columns
```

### 创建新迁移

```bash
# 创建新的迁移脚本
python migrations/migrate.py create add_user_table

# 支持多个单词（用空格分隔）
python migrations/migrate.py create "add user preferences"
```

这将自动创建一个格式为 `20260305_123456_add_user_table.py` 的文件。

## 📝 迁移文件结构

每个迁移文件包含以下结构：

```python
"""迁移描述"""

NAME = "迁移的简短名称"


def up(conn):
    """应用迁移（升级数据库）"""
    conn.execute("""
        ALTER TABLE usage_records 
        ADD COLUMN new_field TEXT DEFAULT ''
    """)


def down(conn):
    """回滚迁移（可选）"""
    conn.execute("ALTER TABLE usage_records DROP COLUMN new_field")
```

### 关键要素

- **版本号**: 文件名前缀（如 `001` 或 `20260305_123456`）
- **NAME**: 迁移的描述性名称
- **up(conn)**: 必需，执行迁移的逻辑
- **down(conn)**: 可选，回滚迁移的逻辑

## 🔄 迁移执行方式

### 方式一：自动迁移（推荐用于开发）

应用程序启动时会自动检测并执行待应用的迁移，无需手动干预：

```python
class SQLiteBillingTracker:
    def __init__(self, settings: BillingSettings):
        self._run_migrations()  # 自动执行迁移
```

**优点**：无需额外操作，开箱即用  
**适用场景**：开发环境、个人使用

### 方式二：手动迁移（推荐用于生产）

在启动应用前，先手动执行迁移检查：

```bash
# 1. 查看迁移状态
python migrations/migrate.py status

# 2. 执行迁移（如有待应用的）
python migrations/migrate.py migrate

# 3. 启动应用
python -m my_openai_robot "你好"
```

**优点**：
- 可控性强，避免启动时的意外
- 便于在生产环境中审查迁移
- 可以在部署脚本中明确调用

**适用场景**：生产环境、团队协作

### 建议的部署流程

```bash
#!/bin/bash
# deploy.sh

# 1. 备份数据库
sqlite3 data/billing.db ".backup data/billing.backup.$(date +%Y%m%d).db"

# 2. 查看待应用的迁移
python migrations/migrate.py status

# 3. 执行迁移
python migrations/migrate.py migrate

# 4. 启动服务
python -m my_openai_robot
```

## 📂 现有迁移

### 001_init.py
- 创建初始 `usage_records` 表
- 包含基础字段：timestamp, prompt_tokens, completion_tokens, cost_usd

### 002_add_speech_columns.py
- 添加语音服务相关字段
- 新字段：stt_duration_seconds, tts_characters, llm_cost, stt_cost, tts_cost
- 智能检测并只添加缺失的列

## 🛠️ 高级用法

### 手动执行迁移

```python
from pathlib import Path
from migrations.migration_runner import MigrationRunner

runner = MigrationRunner(
    db_path=Path("data/billing.db"),
    migrations_dir=Path("migrations")
)

# 查看待执行的迁移
pending = runner.get_pending_migrations()
print(f"待执行: {len(pending)} 个迁移")

# 执行迁移
runner.migrate()
```

### 回滚迁移

```python
# 加载特定迁移
migration = runner._load_migration_file(Path("migrations/002_add_speech_columns.py"))

# 回滚
runner.rollback_migration(migration)
```

## 💡 最佳实践

1. **单一数据源原则**
   - 数据库结构变更只通过迁移脚本管理
   - 不在应用代码中直接创建表或修改结构
   - `billing_tracker.py` 只负责业务逻辑，不处理 DDL

2. **命名规范**
   - 使用描述性的名称：`add_user_table`, `remove_old_fields`
   - 避免使用特殊字符，使用下划线分隔单词

3. **编写 down() 函数**
   - 尽量为每个迁移提供回滚逻辑
   - SQLite 不支持 `DROP COLUMN`，需要重建表

4. **测试迁移**
   - 在开发环境先测试迁移脚本
   - 确保 up() 和 down() 都能正常工作

5. **版本控制**
   - 将迁移文件纳入 Git 版本控制
   - 不要修改已应用的迁移文件

6. **数据备份**
   - 在生产环境执行迁移前备份数据库
   - 使用 `sqlite3 billing.db ".backup backup.db"` 备份

## 🔍 与其他工具对比

| 特性 | 本系统 | Alembic | Django Migrations |
|------|--------|---------|-------------------|
| 依赖 | 无外部依赖 | 需要 SQLAlchemy | 需要 Django |
| 学习成本 | 低 | 中等 | 中等 |
| 自动生成迁移 | ❌ | ✅ | ✅ |
| 轻量级 | ✅ | ❌ | ❌ |
| 适用场景 | 小型项目 | 中大型项目 | Django 项目 |

## 🐛 故障排除

### 迁移未自动执行

检查 `migrations` 目录是否存在且包含迁移文件。

### 迁移历史表损坏

```bash
# 重建迁移历史（谨慎使用）
sqlite3 data/billing.db "DROP TABLE IF EXISTS __migration_history"
python migrations/migrate.py migrate
```

### 迁移执行失败

查看错误信息，检查：
- SQL 语法是否正确
- 表结构是否已存在
- 数据库文件权限

## 📚 参考资料

- [SQLite ALTER TABLE](https://www.sqlite.org/lang_altertable.html)
- [EF Core Migrations](https://learn.microsoft.com/ef/core/managing-schemas/migrations/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
