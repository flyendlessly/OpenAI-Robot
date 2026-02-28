# Azure OpenAI 语音机器人

本项目为 Raspberry Pi OS 友好的 Python 应用，目标是在本地麦克风/扬声器上实现中文语音交互，并通过 Azure OpenAI 与 Azure Speech 服务完成对话推理与语音合成，同时记录资源消耗以适应每月 150 美元的额度限制。

## 特性

- 🤖 使用官方 **OpenAI Python SDK** 调用 Azure OpenAI 服务
- 🎤 支持本地麦克风语音输入与扬声器播放
- 💰 内置费用追踪，自动监控月度预算
- 🔧 模块化设计，易于扩展和维护
- 🌐 自动绕过代理，适配企业网络环境

## 目录结构

```
my-openai-robot/
├── pyproject.toml          # 基于 setuptools 的打包配置
├── requirements.txt        # 运行依赖清单
├── README.md               # 项目说明
├── .env                    # 环境配置（需自行创建）
├── data/                   # 本地存储（如费用数据库）
└── my_openai_robot/
    ├── __init__.py
    ├── __main__.py           # CLI 入口：`python -m my_openai_robot`
    ├── config.py             # Pydantic 配置聚合（Azure、Speech、计费）
    ├── audio_io.py           # 音频输入/输出抽象
    ├── speech_service.py     # STT/TTS 适配层
    ├── llm_client.py         # Azure OpenAI 调用封装（使用 OpenAI SDK）
    ├── conversation_manager.py # 对话编排与状态管理
    └── billing_tracker.py    # Token/费用记录与预算监控
```

## 初步实现计划

1. **配置与依赖**：
   - 通过 `.env` 或系统环境变量提供 `AZURE_OPENAI_ENDPOINT`、`AZURE_OPENAI_API_KEY`、`AZURE_OPENAI_DEPLOYMENT` 等参数；
   - `AppConfig.from_env()` 负责加载并在 CLI 中打印当前关键配置，便于验证。

2. **模块职责**：
   - `audio_io`：后续在 Raspberry Pi 上接入 `sounddevice`/`PyAudio`，实现流式录音与播放；
   - `speech_service`：抽象 Azure Speech STT/TTS，支持切换 Whisper 或其它离线方案；
   - `llm_client`：使用 **OpenAI Python SDK** 封装 Azure OpenAI Chat Completions，自动绕过代理（`trust_env=False`）；
   - `conversation_manager`：统一处理“音频 → 文本 → LLM → 文本 → 音频”的闭环及错误重试；
   - `billing_tracker`：解析 Azure usage 字段，换算成本，持久化到 `data/billing.db` 并在逼近额度时提示。

3. **开发进度**：
   - [x] 完成 `llm_client` 与 `config`，使用 AzureOpenAI SDK 实现文本 CLI 调试
   - [x] 集成费用统计与预算告警
   - [x] 接入音频 I/O，实现麦克风录音与扬声器播放
   - [x] 集成 Azure Speech，完成 STT/TTS 实时语音循环
   - [ ] 添加唤醒词检测（考虑 Porcupine 或按键触发）
   - [ ] 优化 Raspberry Pi 部署（systemd 服务、依赖裁剪）

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

### 2. 配置 Azure 服务

创建 `.env` 文件并填入你的 Azure 凭证：

```dotenv
# Azure OpenAI 配置
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-5.1-chat

# Azure Speech 配置（语音功能必需）
AZURE_SPEECH_KEY=your-speech-key
AZURE_SPEECH_REGION=eastus
AZURE_SPEECH_STT_ENDPOINT=https://eastus.stt.speech.microsoft.com
AZURE_SPEECH_TTS_ENDPOINT=https://eastus.tts.speech.microsoft.com
AZURE_SPEECH_STT_LANGUAGE=zh-CN
AZURE_SPEECH_VOICE=zh-CN-XiaoxiaoNeural

# 费用追踪配置
ENABLE_BILLING=true
BILLING_PROVIDER=sqlite
MONTHLY_BUDGET_USD=150
BUDGET_WARN_RATIO=0.9
BILLING_DB_PATH=data/billing.db
PROMPT_COST_PER_1K=0.15
COMPLETION_COST_PER_1K=0.6
```

**重要提示**：
- 使用 `AzureOpenAI` SDK 时，`AZURE_OPENAI_ENDPOINT` 只需基础域名（`cognitiveservices.azure.com/` 结尾，**不要**加 `/openai/v1/`）
- `AZURE_OPENAI_DEPLOYMENT` 填写你在 Azure Portal 中创建的部署名称（不是模型名）
- 某些模型（如 gpt-5.1-chat）只支持特定参数，如 `temperature=1.0` 和 `max_completion_tokens`
- 成本单价需根据你实际使用的模型调整

### 3. 文本 CLI 调试

在配置好 `.env` 之后，可直接发送单轮提示或进入交互模式：

```bash
# 单轮对话
python -m my_openai_robot "你好，请介绍一下自己"

# 交互模式
python -m my_openai_robot

# 自定义参数（注意：某些模型只支持 temperature=1.0）
python -m my_openai_robot "讲个笑话" --max-tokens 1024
```

输出示例：
```
--- AI 回复 ---
你好！我是你的中文语音助手，很高兴能帮助你...

--- 用量 ---
{
  "prompt_tokens": 26,
  "completion_tokens": 59,
  "total_tokens": 85
}
本次预估费用: $0.039300
本月累计费用: $0.0393 / $150.00
```

CLI 会输出 Azure LLM 的回复、`usage` 字段以及预估费用/本月累计花费；若达到预算告警阈值会提示 ⚠。

### 4. 语音对话模式（可选）

前置条件：

- Azure Speech 服务已开通，并在 `.env` 中配置 `AZURE_SPEECH_KEY`、`AZURE_SPEECH_REGION`；
- 本地已安装麦克风/扬声器驱动以及 `sounddevice`、`numpy` 依赖（已包含在 `requirements.txt`）；
- Raspberry Pi OS 上建议先运行 `sudo apt install libportaudio2` 以避免驱动缺失。

运行前先测试设备：

```bash
# 列出所有音频设备
python -m my_openai_robot --list-devices

# 测试麦克风（录制 3 秒）
python -m my_openai_robot --test-microphone --record-seconds 3

# 指定设备测试（如果默认设备不工作）
python -m my_openai_robot --test-microphone --input-device 5
```

语音对话：

```bash
# 基本语音对话
python -m my_openai_robot --voice-turn --record-seconds 5

# 保存 AI 回复音频
python -m my_openai_robot --voice-turn --record-seconds 5 --save-reply-audio reply.wav

# 指定音频设备
python -m my_openai_robot --voice-turn --input-device 5 --output-device 3
```

流程说明：

- CLI 会提示开始录音，采集 `record-seconds` 指定的秒数；
- 实时显示录音进度条和音量指示器；
- 通过 Azure Speech 识别文本，再由 ConversationManager 调用 Azure OpenAI 生成回复；
- 默认使用 Azure Speech 合成语音并通过扬声器播放，若提供 `--save-reply-audio` 则额外输出 WAV 文件；
- 同样会展示 usage/费用信息，方便监控额度。

输出示例：
```
============================================================
准备录制语音（5.0 秒）
请在提示后开始说话...
============================================================

开始录音 5.0 秒...
进度: [█████████████████████████████░] 99% | 音量: [▮▮▮▮▮▯▯▯▯▯]
录音完成！

正在识别语音...

✓ 识别结果: 你好呀你能为我做什么？

============================================================
AI 回复:
============================================================
你好！很高兴能帮到你。我可以为你做很多事情，比如：
- 回答问题：无论是生活常识、学习问题还是其他方面的疑问...
============================================================
--- 用量 ---
{
  "prompt_tokens": 29,
  "completion_tokens": 148,
  "total_tokens": 177
}
本次预估费用: $0.093150
本月累计费用: $1.0809 / $150.00

正在播放回复...
✓ 播放完成
```

## 配置说明

### 费用追踪

通过以下环境变量自定义预算与 token 单价（默认按 `gpt-4o-mini` 估值，可根据实际模型调整）：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `ENABLE_BILLING` | 是否启用本地计费追踪 | `true` |
| `BILLING_PROVIDER` | 计费插件，当前支持 `sqlite` | `sqlite` |
| `MONTHLY_BUDGET_USD` | 每月可用额度（美元） | `150` |
| `BUDGET_WARN_RATIO` | 告警比例，0.9 表示 90% 触发提示 | `0.9` |
| `PROMPT_COST_PER_1K` | 提示 token 单价（美元/千 token） | `0.15` |
| `COMPLETION_COST_PER_1K` | 回答 token 单价（美元/千 token） | `0.6` |
| `BILLING_DB_PATH` | 费用 SQLite 存储路径 | `data/billing.db` |

默认提供 `sqlite` 插件，通过 `BILLING_PROVIDER=sqlite` 写入 `data/billing.db`；也可以使用 `register_billing_provider()` 注册自定义实现（例如远端 API、JSON 文件）。若需完全禁用计费，可设置 `ENABLE_BILLING=false`。

### 代理与网络

项目自动绕过系统代理设置（通过 `trust_env=False`），适合企业网络环境。如果遇到连接问题：

1. **检查 endpoint 格式**：使用 `AzureOpenAI` 时应为 `https://xxx.cognitiveservices.azure.com/`（**无需** `/openai/v1/` 后缀）
2. **验证部署名称**：在 Azure Portal 中确认实际的 deployment 名称
3. **检查 API 版本**：较新的模型需要使用 `2024-12-01-preview` 或更新版本
4. **测试连接**：使用 `curl` 或 `Invoke-RestMethod` 验证 Azure 服务可达性

### Azure 服务终结点

| 服务 | 终结点格式示例 |
| --- | --- |
| Azure OpenAI（AzureOpenAI SDK） | `https://your-resource.cognitiveservices.azure.com/` |
| Azure OpenAI（通用 OpenAI SDK） | `https://your-resource.services.ai.azure.com/openai/v1/` |
| Azure Speech STT | `https://eastus.stt.speech.microsoft.com` |
| Azure Speech TTS | `https://eastus.tts.speech.microsoft.com` |

**推荐使用 AzureOpenAI SDK**（本项目已采用），endpoint 格式更简洁，自动处理 API 路径。

## 技术栈

- **OpenAI Python SDK** - 官方 SDK 调用 Azure OpenAI
- **Azure Cognitive Services Speech** - 语音识别与合成
- **Pydantic** - 配置管理与验证
- **SQLAlchemy** - 费用数据持久化
- **sounddevice** - 音频 I/O
- **httpx** - HTTP 客户端（OpenAI SDK 依赖）

## 故障排查

### 404 Resource not found

检查：
- `AZURE_OPENAI_ENDPOINT` 格式：使用 `AzureOpenAI` 时应为 `https://xxx.cognitiveservices.azure.com/`（**不要**加 `/openai/v1/`）
- `AZURE_OPENAI_DEPLOYMENT` 是否与 Azure Portal 中的部署名称完全一致
- `AZURE_OPENAI_API_VERSION` 是否支持该模型（推荐 `2024-12-01-preview`）

### 400 Bad Request - Unsupported parameter

某些新模型（如 gpt-5.1-chat）有参数限制：
- `max_tokens` → 使用 `max_completion_tokens`（代码已自动处理）
- `temperature` 只支持默认值 `1.0`（代码已自动适配）

### 语音识别失败或音量过低

```bash
# 列出音频设备
python -m my_openai_robot --list-devices

# 测试麦克风
python -m my_openai_robot --test-microphone --record-seconds 3

# 使用特定设备
python -m my_openai_robot --voice-turn --input-device <设备ID>
```

### SSL/代理错误

项目已配置 `trust_env=False` 自动绕过代理。如仍有问题，手动清除环境变量：

```powershell
# PowerShell
[Environment]::SetEnvironmentVariable('HTTP_PROXY', $null, 'Process')
[Environment]::SetEnvironmentVariable('HTTPS_PROXY', $null, 'Process')
```

```bash
# Linux/macOS
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
```

### 音频设备问题

Raspberry Pi 上确保安装音频驱动：
```bash
sudo apt install libportaudio2 alsa-utils
arecord -l  # 列出录音设备
aplay -l    # 列出播放设备
```

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可

MIT License
