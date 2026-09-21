# Raspberry Pi 部署与维护指南

本指南专为在树莓派（Raspberry Pi 4B / 5 等设备）上常驻运行 Azure OpenAI 语音助手设计，涵盖了系统要求、硬件适配、一键部署、systemd 守护进程常驻以及 SD 卡保护调优。

---

## 📋 准备与系统要求

| 类别 | 要求 / 推荐配置 | 说明 |
| :--- | :--- | :--- |
| **硬件平台** | Raspberry Pi 4B / 5 (推荐 2GB 及以上内存) | 运算与音频处理更稳定 |
| **操作系统** | **Raspberry Pi OS 64-bit** (Debian Bookworm) | ⚠️ **必须 64 位 (aarch64)**，Azure Speech SDK 官方不提供 32 位轮子 |
| **音频输入** | USB 麦克风 或 ReSpeaker 阵列 | 板载无输入设备，需外接麦克风 |
| **音频输出** | 3.5mm 音箱、USB 音箱 或 HDMI 音频 | 提供清晰的 TTS 语音回放 |
| **网络环境** | 稳定的 Wi-Fi 或有线以太网 | 保证与 Azure OpenAI / Speech 服务的低延迟交互 |

---

## 🚀 方式一：一键自动化部署（推荐）

我们在 [deploy/deploy_pi.sh](deploy/deploy_pi.sh) 提供了全自动安装脚本，会自动安装底层编译依赖（ALSA/PortAudio）、创建虚拟环境、安装依赖、配置音频用户组并注册 systemd 服务。

在树莓派终端中执行：

```bash
# 1. 克隆代码或进入项目目录
cd /opt/my-openai-robot  # 或你的项目实际目录

# 2. 为部署脚本赋予执行权限并运行
chmod +x deploy/deploy_pi.sh
./deploy/deploy_pi.sh
```

脚本将自动完成：
1. 校验 CPU 架构是否为 64 位（`aarch64` / `x86_64`）；
2. 通过 `apt` 安装 `portaudio19-dev`, `libasound2-dev`, `alsa-utils`, `python3-venv` 等底层组件；
3. 将当前操作用户加入 `audio` 用户组；
4. 构建 Python 虚拟环境 `.venv` 并安装 [requirements.txt](../requirements.txt)；
5. 生成针对当前路径与用户的 systemd 守护进程单元文件并完成注册。

---

## 🛠️ 方式二：手动分步部署

如果你希望完全掌控每一步流程，请参照以下步骤：

### 1. 安装系统底层依赖
```bash
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip python3-dev build-essential \
                        portaudio19-dev libasound2-dev alsa-utils
sudo usermod -aG audio $USER
```

### 2. 构建虚拟环境并安装 Python 依赖
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### 3. 配置凭据环境
```bash
cp .env.example .env
nano .env  # 填入你的 Azure OpenAI 和 Speech 凭证
```

---

## 🔊 音频设备配置与防漂移

树莓派重启或拔插 USB 麦克风后，设备序号（Card ID）可能发生变化。

### 1. 检查声卡设备
```bash
# 激活环境
source .venv/bin/activate

# 打印所有检测到的音频设备
python -m my_openai_robot --list-devices

# 测试指定麦克风输入（说话时终端会打印音量条）
python -m my_openai_robot --test-microphone
```

### 2. 固定输入/输出设备
如果系统识别出麦克风为设备 `1`，扬声器为设备 `0`，可直接在命令行附加参数：
```bash
python -m my_openai_robot --wake-word --use-vad --stream --input-device 1 --output-device 0
```

---

## 🤖 systemd 守护进程服务管理

部署完成后，助手将作为后台守护进程常驻运行，崩溃后 5 秒自动拉起。

### 常用运维命令
* **启动服务**：
  ```bash
  sudo systemctl start openai-robot
  ```
* **设置开机自启**：
  ```bash
  sudo systemctl enable openai-robot
  ```
* **查看服务状态**：
  ```bash
  sudo systemctl status openai-robot
  ```
* **查看实时日志 (追踪对话与唤醒)**：
  ```bash
  journalctl -u openai-robot -f
  ```
* **重启服务**：
  ```bash
  sudo systemctl restart openai-robot
  ```
* **停止服务**：
  ```bash
  sudo systemctl stop openai-robot
  ```

---

## ⚡ 树莓派专属优化技巧

### 1. 保护 SD 卡寿命（日志易失存储）
频繁向 MicroSD 卡写日志易缩短存储卡寿命。建议将 systemd 日志配置为仅保留在内存（volatile）中：
编辑 `/etc/systemd/journald.conf`：
```ini
[Journal]
Storage=volatile
RuntimeMaxUse=64M
```
然后执行 `sudo systemctl restart systemd-journald` 即可。

### 2. 避免音频进入节能挂起
树莓派的某些 USB 麦克风或板载音频可能在空闲时被系统电源管理挂起，导致唤醒词初次监听延迟。可通过创建或修改 `/etc/modprobe.d/audio_powersave.conf`：
```ini
options snd_usb_audio power_save=0
```

### 3. 内存与 CPU 负载监控
服务单元文件已限制 `MemoryHigh=350M` 和 `MemoryMax=512M`。通过以下命令观察树莓派资源：
```bash
systemd-cgtop
```

### 4. 软件声学回声消除（AEC）配置（防扬声器自听与回音抑制）
当麦克风与扬声器距离较近时，扬声器播放的声音易被麦克风录入，导致“自言自语”或误触发。若硬件无 DSP 降噪芯片，推荐启用 Linux 系统级 WebRTC 回声消除模块：

1. **安装并临时测试加载**：
   ```bash
   sudo apt-get install -y pulseaudio pulseaudio-utils
   # 加载 PulseAudio 自带的 WebRTC 回声消除模块（自动关联默认输入与输出）
   pactl load-module module-echo-cancel aec_method=webrtc
   ```
2. **验证虚拟回声消除设备**：
   运行以下命令，确认已生成 `echo-cancel-source` 虚拟音频源：
   ```bash
   pactl list sources short | grep echo-cancel
   ```
3. **开机持久化配置**：
   编辑 `/etc/pulse/default.pa`（或用户目录 `~/.config/pulse/default.pa`），在末尾追加：
   ```ini
   # 启用 WebRTC 回声消除模块并设为默认输入源
   load-module module-echo-cancel aec_method=webrtc
   set-default-source echo-cancel-source
   ```
4. **与本助手集成**：
   启动助手时，通过 `python -m my_openai_robot --list-devices` 找到该虚拟设备的编号，作为 `--input-device` 传入即可。

