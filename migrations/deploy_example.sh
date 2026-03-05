#!/bin/bash
# 数据库迁移部署脚本示例（Bash）
# 用于生产环境部署时的数据库迁移

set -e  # 遇到错误立即退出

DRY_RUN=false

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "未知参数: $1"
            echo "用法: $0 [--dry-run]"
            exit 1
            ;;
    esac
done

echo -e "\033[1;36m=== 数据库迁移部署 ===\033[0m"
echo ""

# 1. 备份数据库
BACKUP_PATH="data/billing.backup.$(date +%Y%m%d_%H%M%S).db"
if [ -f "data/billing.db" ]; then
    echo -e "\033[1;33m📦 备份数据库...\033[0m"
    cp "data/billing.db" "$BACKUP_PATH"
    echo -e "   \033[1;32m✅ 已备份到: $BACKUP_PATH\033[0m"
else
    echo -e "\033[0;37mℹ️  数据库文件不存在，跳过备份\033[0m"
fi

# 2. 查看迁移状态
echo ""
echo -e "\033[1;33m📊 检查迁移状态...\033[0m"
python migrations/migrate.py status

# 3. 执行迁移（除非是试运行模式）
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo -e "\033[0;37mℹ️  试运行模式：不执行迁移\033[0m"
    echo -e "   要执行迁移，请运行: ./migrations/deploy_example.sh"
else
    echo ""
    echo -e "\033[1;33m🚀 执行迁移...\033[0m"
    
    if python migrations/migrate.py migrate; then
        echo ""
        echo -e "\033[1;32m✅ 迁移部署成功！\033[0m"
    else
        echo ""
        echo -e "\033[1;31m❌ 迁移执行失败！正在恢复备份...\033[0m"
        if [ -f "$BACKUP_PATH" ]; then
            cp "$BACKUP_PATH" "data/billing.db"
            echo -e "\033[1;32m✅ 已恢复备份\033[0m"
        fi
        exit 1
    fi
fi

echo ""
echo -e "\033[1;36m=== 完成 ===\033[0m"
