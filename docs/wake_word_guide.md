# 离线开源唤醒词功能使用指南 (Sherpa-ONNX)

基于 k2-fsa/Sherpa-ONNX（基于 Next-gen Kaldi 与 ONNX Runtime）实现的离线开源唤醒词检测功能，零 API Key、零云端授权限制，原生支持自定义中文唤醒词与播放随时打断（Barge-in）。

## 🎯 功能特性

- ✅ **完全开源离线**：无需注册账号、无需 API Key，100% 本地端侧运行，零隐私外泄风险。
- ✅ **无设备数限制**：开源无绑机限制，支持 Windows / Linux / macOS / 树莓派 (ARM64) 任意部署。
- ✅ **原生支持中文与自定义**：支持任意中文唤醒词（自动转拼音音素，免从头训练模型）。
- ✅ **支持随时打断 (Barge-in)**：AI 回复播报期间，随时喊出唤醒词可立即打断播放并开始新一轮倾听。
- ✅ **持续监听**：检测到唤醒词后自动开始对话，对话结束后自动继续监听。

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install sherpa-onnx pypinyin
```

### 2. 准备离线预训练模型

系统支持启动时一键自动拉取轻量级中文 Zipformer 模型 (~30MB)，也可以通过命令行预先下载：

```bash
python -m my_openai_robot --download-wake-model
```

### 3. 配置环境变量

在 `.env` 文件中配置：

```bash
# 启用唤醒词
ENABLE_WAKE_WORD=true

# 唤醒词引擎（sherpa-onnx）
WAKE_WORD_BACKEND=sherpa-onnx

# 配置唤醒词（逗号分隔，支持多个）
WAKE_WORD_KEYWORDS=芝麻开门,你好小智,小智小智

# 灵敏度阈值（0.0-1.0，默认 0.25，越小越灵敏）
WAKE_WORD_THRESHOLD=0.25

# 评分增强系数（默认 1.5）
WAKE_WORD_SCORE=1.5
```

### 4. 运行唤醒词模式

```bash
python -m my_openai_robot --wake-word --use-vad
```
