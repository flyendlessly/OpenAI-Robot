"""数据库迁移运行器 - 类似 EF Migrations"""
from __future__ import annotations

import importlib.util
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, List


@dataclass
class Migration:
    """迁移脚本元数据"""
    version: str  # 如: "001_init" 或 "20260305_add_speech_columns"
    name: str
    file_path: Path
    up: Callable[[sqlite3.Connection], None]
    down: Callable[[sqlite3.Connection], None] | None = None


class MigrationRunner:
    """迁移管理器，负责执行和记录迁移"""
    
    def __init__(self, db_path: Path, migrations_dir: Path | None = None):
        self.db_path = db_path
        if migrations_dir is None:
            migrations_dir = Path(__file__).parent
        self.migrations_dir = migrations_dir
        self._ensure_db_exists()
        self._init_migration_table()
    
    def _ensure_db_exists(self) -> None:
        """确保数据库文件存在（即使为空）"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self.db_path.touch()
    
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """数据库连接上下文"""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_migration_table(self) -> None:
        """创建迁移历史表"""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS __migration_history (
                    version TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
    
    def _get_applied_versions(self) -> set[str]:
        """获取已执行的迁移版本"""
        with self._connect() as conn:
            cursor = conn.execute("SELECT version FROM __migration_history")
            return {row[0] for row in cursor.fetchall()}
    
    def _load_migration_file(self, file_path: Path) -> Migration:
        """动态加载迁移脚本文件"""
        spec = importlib.util.spec_from_file_location("migration", file_path)
        if not spec or not spec.loader:
            raise ImportError(f"无法加载迁移文件: {file_path}")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # 从文件名提取版本号，格式: 001_init.py 或 20260305_add_columns.py
        version = file_path.stem
        
        return Migration(
            version=version,
            name=getattr(module, "NAME", version),
            file_path=file_path,
            up=module.up,
            down=getattr(module, "down", None),
        )
    
    def discover_migrations(self) -> List[Migration]:
        """扫描并加载所有迁移脚本"""
        migrations = []
        for file_path in sorted(self.migrations_dir.glob("*.py")):
            # 跳过内部文件和工具脚本
            if file_path.name.startswith("_") or file_path.name in ("migrate.py", "migration_runner.py"):
                continue
            try:
                migration = self._load_migration_file(file_path)
                migrations.append(migration)
            except Exception as e:
                print(f"⚠️  加载迁移失败 {file_path.name}: {e}")
        return migrations
    
    def get_pending_migrations(self) -> List[Migration]:
        """获取待执行的迁移"""
        applied = self._get_applied_versions()
        all_migrations = self.discover_migrations()
        return [m for m in all_migrations if m.version not in applied]
    
    def apply_migration(self, migration: Migration) -> None:
        """执行单个迁移"""
        print(f"🔄 应用迁移: {migration.version} - {migration.name}")
        
        with self._connect() as conn:
            # 执行迁移
            migration.up(conn)
            
            # 记录到历史表
            conn.execute(
                "INSERT INTO __migration_history (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, datetime.utcnow().isoformat()),
            )
        
        print(f"✅ 完成: {migration.version}")
    
    def rollback_migration(self, migration: Migration) -> None:
        """回滚单个迁移"""
        if not migration.down:
            raise ValueError(f"迁移 {migration.version} 没有提供 down() 回滚函数")
        
        print(f"⏪ 回滚迁移: {migration.version}")
        
        with self._connect() as conn:
            # 执行回滚
            migration.down(conn)
            
            # 从历史表删除
            conn.execute("DELETE FROM __migration_history WHERE version = ?", (migration.version,))
        
        print(f"✅ 回滚完成: {migration.version}")
    
    def migrate(self, target_version: str | None = None) -> None:
        """执行所有待应用的迁移（或迁移到指定版本）"""
        pending = self.get_pending_migrations()
        
        if not pending:
            print("✅ 数据库已是最新版本，无需迁移")
            return
        
        if target_version:
            # 只执行到指定版本
            pending = [m for m in pending if m.version <= target_version]
        
        print(f"\n📦 发现 {len(pending)} 个待执行的迁移:\n")
        for migration in pending:
            self.apply_migration(migration)
        
        print(f"\n🎉 迁移完成！")
    
    def status(self) -> None:
        """显示迁移状态"""
        applied = self._get_applied_versions()
        all_migrations = self.discover_migrations()
        
        print("\n📊 数据库迁移状态:\n")
        print(f"{'版本':<25} {'状态':<10} {'名称'}")
        print("-" * 60)
        
        for migration in all_migrations:
            status = "✅ 已应用" if migration.version in applied else "⏸️  待执行"
            print(f"{migration.version:<25} {status:<10} {migration.name}")
        
        pending_count = len([m for m in all_migrations if m.version not in applied])
        print(f"\n总计: {len(all_migrations)} 个迁移，{len(applied)} 个已应用，{pending_count} 个待执行")


def create_migration_file(name: str, migrations_dir: Path | None = None) -> Path:
    """创建新的迁移脚本文件"""
    if migrations_dir is None:
        migrations_dir = Path(__file__).parent
    
    # 规范化名称：转换为小写，用下划线替换空格和特殊字符
    name = name.strip().lower()
    name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    name = "_".join(filter(None, name.split("_")))  # 去除连续下划线
    
    # 生成版本号：日期时间格式
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{version}_{name}.py"
    file_path = migrations_dir / filename
    
    # 生成模板
    template = f'''"""迁移: {name}

创建时间: {datetime.now().isoformat()}
"""

NAME = "{name}"


def up(conn):
    """应用迁移（升级数据库）"""
    # TODO: 在此编写 DDL 语句
    # 示例:
    # conn.execute("""
    #     ALTER TABLE usage_records 
    #     ADD COLUMN new_field TEXT DEFAULT ''
    # """)
    pass


def down(conn):
    """回滚迁移（可选）"""
    # TODO: 编写回滚逻辑
    # 示例:
    # conn.execute("ALTER TABLE usage_records DROP COLUMN new_field")
    pass
'''
    
    file_path.write_text(template, encoding="utf-8")
    print(f"✅ 已创建迁移文件: {file_path}")
    return file_path
