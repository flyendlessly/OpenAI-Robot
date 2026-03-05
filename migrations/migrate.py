#!/usr/bin/env python3
"""数据库迁移命令行工具

用法:
    python migrations/migrate.py [命令]

命令:
    status              查看迁移状态
    migrate             执行所有待执行的迁移
    migrate [version]   迁移到指定版本
    create [名称]       创建新的迁移脚本
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from my_openai_robot.config import AppConfig
from migrations.migration_runner import MigrationRunner, create_migration_file


def main():
    # 加载配置获取数据库路径
    try:
        config = AppConfig.from_env()
        db_path = config.billing.storage_path
    except Exception:
        # 如果配置加载失败，使用默认路径
        db_path = Path("data/billing.db")
    
    migrations_dir = Path(__file__).parent
    runner = MigrationRunner(db_path, migrations_dir)
    
    # 解析命令行参数
    args = sys.argv[1:]
    
    if not args or args[0] == "status":
        runner.status()
    
    elif args[0] == "migrate":
        target_version = args[1] if len(args) > 1 else None
        runner.migrate(target_version)
    
    elif args[0] == "create":
        if len(args) < 2:
            print("❌ 错误: 请提供迁移名称")
            print("   用法: python migrations/migrate.py create <名称>")
            sys.exit(1)
        
        name = "_".join(args[1:])  # 支持多个单词
        create_migration_file(name, migrations_dir)
    
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
