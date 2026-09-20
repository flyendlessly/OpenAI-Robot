#!/usr/bin/env bash
# ==============================================================================
# Azure OpenAI 语音助手 - 树莓派 (Raspberry Pi) 一键自动化部署脚本
# ==============================================================================

set -eo pipefail

# 终端色彩定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${CYAN}${BOLD}======================================================${NC}"
echo -e "${CYAN}${BOLD}   Azure OpenAI 语音助手 (my-openai-robot) 树莓派部署   ${NC}"
echo -e "${CYAN}${BOLD}======================================================${NC}"
echo ""

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="${SUDO_USER:-$USER}"
SERVICE_NAME="openai-robot"
SYSTEMD_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

# 1. 架构检测 (Azure Speech SDK 强依赖 64 位系统)
ARCH="$(uname -m)"
echo -e "${YELLOW}🔍 检查系统硬件架构: ${ARCH}${NC}"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "x86_64" ]]; then
    echo -e "${RED}⚠️  警告: 当前架构为 ${ARCH}。${NC}"
    echo -e "${RED}   azure-cognitiveservices-speech 官方仅支持 64 位系统 (aarch64 / x86_64)。${NC}"
    echo -e "${RED}   如果运行的是 32 位系统 (如 armv7l)，可能会在 pip 安装或运行时报错！${NC}"
    read -rp "是否仍要继续尝试安装？(y/N): " choice
    if [[ "$choice" != [yY] && "$choice" != [yY][eE][sS] ]]; then
        echo "已终止部署。"
        exit 1
    fi
else
    echo -e "${GREEN}✅ 系统架构 (${ARCH}) 符合 64 位运行要求。${NC}"
fi

# 2. 安装系统级依赖
echo ""
echo -e "${YELLOW}📦 [1/5] 安装系统底层音频及编译依赖...${NC}"
sudo apt-get update -y
sudo apt-get install -y \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    portaudio19-dev \
    libasound2-dev \
    libatlas-base-dev \
    alsa-utils \
    sox \
    libsox-fmt-all

# 3. 配置当前用户音频组权限
echo ""
echo -e "${YELLOW}🔒 [2/5] 配置音频设备访问权限...${NC}"
sudo usermod -aG audio "$CURRENT_USER"
echo -e "${GREEN}✅ 用户 $CURRENT_USER 已加入 audio 组。${NC}"

# 4. 创建 Python 虚拟环境并安装项目依赖
echo ""
echo -e "${YELLOW}🐍 [3/5] 配置 Python 虚拟环境与核心依赖...${NC}"
cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
    echo "创建虚拟环境: $PROJECT_DIR/.venv"
    python3 -m venv .venv
fi

# 激活虚拟环境安装
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .

# 5. 检查并引导配置 .env
echo ""
echo -e "${YELLOW}⚙️  [4/5] 检查环境配置文件...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}未检测到 .env，正在从 .env.example 生成模板...${NC}"
        cp .env.example .env
        echo -e "${GREEN}✅ 已创建 $PROJECT_DIR/.env，请务必稍后填入真实 API 密钥！${NC}"
    else
        echo -e "${RED}⚠️  未找到 .env.example，请手动创建 .env 文件！${NC}"
    fi
else
    echo -e "${GREEN}✅ 已检测到现有 .env 配置文件。${NC}"
fi

# 6. 生成并注册 systemd 守护进程
echo ""
echo -e "${YELLOW}🤖 [5/5] 配置 systemd 守护进程 (${SERVICE_NAME}.service)...${NC}"
SERVICE_TMP="/tmp/${SERVICE_NAME}.service"

cat <<EOF > "$SERVICE_TMP"
[Unit]
Description=Azure OpenAI Voice Assistant for Raspberry Pi
After=network-online.target sound.target
Wants=network-online.target sound.target

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR

EnvironmentFile=$PROJECT_DIR/.env
Environment="PYTHONUNBUFFERED=1"
Environment="XDG_RUNTIME_DIR=/run/user/$(id -u "$CURRENT_USER")"

# 默认常驻唤醒词模式 + 智能 VAD 断句 + 流式切句
ExecStart=$PROJECT_DIR/.venv/bin/python -m my_openai_robot --wake-word --use-vad --stream

Restart=always
RestartSec=5s

MemoryHigh=350M
MemoryMax=512M

StandardOutput=journal
StandardError=journal
SyslogIdentifier=openai-robot

[Install]
WantedBy=multi-user.target
EOF

sudo mv "$SERVICE_TMP" "$SYSTEMD_PATH"
sudo chown root:root "$SYSTEMD_PATH"
sudo chmod 644 "$SYSTEMD_PATH"
sudo systemctl daemon-reload

echo -e "${GREEN}✅ systemd 服务已生成: $SYSTEMD_PATH${NC}"

# 7. 部署完成提示与引导
echo ""
echo -e "${CYAN}${BOLD}======================================================${NC}"
echo -e "${GREEN}${BOLD}🎉 树莓派环境部署完成！${NC}"
echo -e "${CYAN}${BOLD}======================================================${NC}"
echo ""
echo -e "后续管理常用命令指引："
echo -e "  1. 编辑密钥配置:    ${BOLD}nano $PROJECT_DIR/.env${NC}"
echo -e "  2. 麦克风录音测试:  ${BOLD}.venv/bin/python -m my_openai_robot --test-microphone${NC}"
echo -e "  3. 启动后台服务:    ${BOLD}sudo systemctl start $SERVICE_NAME${NC}"
echo -e "  4. 设置开机自启:    ${BOLD}sudo systemctl enable $SERVICE_NAME${NC}"
echo -e "  5. 查看实时日志:    ${BOLD}journalctl -u $SERVICE_NAME -f${NC}"
echo -e "  6. 停止后台服务:    ${BOLD}sudo systemctl stop $SERVICE_NAME${NC}"
echo ""
echo -e "${YELLOW}提示: 如果当前用户刚被加入 audio 组，建议重新登录或重启终端生效权限。${NC}"
