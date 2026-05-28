# 唤醒词功能使用指南

通过 Picovoice Porcupine 实现的本地唤醒词检测功能，让你的语音助手像 Alexa、Siri 一样可以被唤醒。

## 🎯 功能特性

- ✅ **本地处理**：唤醒词检测完全在本地运行，无需联网
- ✅ **低延迟**：实时检测，响应迅速
- ✅ **多唤醒词**：支持同时配置多个唤醒词
- ✅ **可调灵敏度**：灵活调整每个唤醒词的检测灵敏度
- ✅ **持续监听**：检测到唤醒词后自动开始对话，对话结束后继续监听

## 🚀 快速开始

### 1. 获取 Picovoice Access Key

1. 访问 [Picovoice Console](https://console.picovoice.ai/)
2. 注册账号（免费）
3. 创建 Access Key
4. 复制密钥

**免费版限制**：
- 每月 3 个设备
- 每个设备无限次检测
- 对个人使用完全够用

### 2. 安装依赖

```bash
pip install pvporcupine
```

### 3. 配置环境变量

在 `.env` 文件中添加：

```bash
# 启用唤醒词
ENABLE_WAKE_WORD=true

# 设置 Access Key
PORCUPINE_ACCESS_KEY=your_access_key_here

# 配置唤醒词（可选，默认为 jarvis,computer）
WAKE_WORD_KEYWORDS=jarvis,computer

# 配置灵敏度（可选，默认 0.5）
WAKE_WORD_SENSITIVITIES=0.5,0.5
```

### 4. 启动唤醒模式

```bash
# 使用 VAD 自动检测说话结束（推荐）
python -m my_openai_robot --wake-word --use-vad

# 固定录音时长
python -m my_openai_robot --wake-word --record-seconds 10
```

## 📝 支持的唤醒词

### 内置唤醒词

Porcupine 提供以下免费的内置唤醒词：

```
alexa          americano      blueberry      bumblebee
computer       grapefruit     grasshopper    hey google
hey siri       jarvis         ok google      picovoice
porcupine      terminator
```

查看完整列表：

```bash
python -m my_openai_robot --list-wake-words
```

### 配置多个唤醒词

```bash
# 同时监听多个唤醒词
WAKE_WORD_KEYWORDS=jarvis,computer,hey siri

# 为每个唤醒词设置不同灵敏度
WAKE_WORD_SENSITIVITIES=0.6,0.5,0.7
```

## ⚙️ 配置说明

### 灵敏度调整

`WAKE_WORD_SENSITIVITIES` 参数控制检测灵敏度（0.0 - 1.0）：

- **0.3 - 0.4**：低灵敏度，减少误报，但可能错过部分唤醒
- **0.5**：默认值，平衡灵敏度和误报率（推荐）
- **0.6 - 0.7**：高灵敏度，更容易唤醒但误报率增加
- **0.8 - 1.0**：极高灵敏度，不推荐（误报率很高）

### 环境变量完整示例

```bash
# 基础配置
ENABLE_WAKE_WORD=true
PORCUPINE_ACCESS_KEY=your_key_here

# 使用 jarvis 和 computer 作为唤醒词
WAKE_WORD_KEYWORDS=jarvis,computer
WAKE_WORD_SENSITIVITIES=0.5,0.5

# 可选：自定义模型路径（高级用户）
# WAKE_WORD_MODEL_PATH=/path/to/custom_model.pv
# WAKE_WORD_KEYWORD_PATHS=/path/to/keyword1.ppn,/path/to/keyword2.ppn
```

## 🎮 使用示例

### 基础用法

```bash
# 启动唤醒词监听（使用 VAD）
python -m my_openai_robot --wake-word --use-vad

# 指定音频设备
python -m my_openai_robot --wake-word --use-vad \\
    --input-device 1 --output-device 2
```

### 完整工作流程

1. **启动监听**
   ```
   🎙️  唤醒词监听模式
   ============================================================
   唤醒词: jarvis, computer
   采样率: 16000 Hz
   帧长度: 512 样本
   
   请说出唤醒词开始对话...
   按 Ctrl+C 退出
   ============================================================
   
   👂 正在监听唤醒词...
   ```

2. **检测到唤醒词**
   ```
   ✨ 检测到唤醒词: jarvis
   ============================================================
   VAD 录音模式（最长 10 秒，静音 2 秒自动停止）
   请在提示后开始说话...
   ```

3. **语音交互**
   ```
   正在识别语音...
   ✓ 识别结果: 今天天气怎么样？
   
   AI 回复:
   ============================================================
   今天天气晴朗，气温约 25 度...
   ============================================================
   
   正在播放回复...
   ✓ 播放完成
   ```

4. **继续监听**
   ```
   ============================================================
   👂 继续监听唤醒词...
   ```

## 🛠️ 高级功能

### 自定义唤醒词

Picovoice 支持训练自定义唤醒词：

1. 访问 [Picovoice Console](https://console.picovoice.ai/)
2. 创建自定义唤醒词（需付费）
3. 下载 `.ppn` 文件
4. 配置路径：

```bash
WAKE_WORD_KEYWORD_PATHS=/path/to/my_wakeword.ppn
```

### 自定义模型

使用特定语言或声学模型：

```bash
WAKE_WORD_MODEL_PATH=/path/to/porcupine_params_zh.pv
```

## 🔧 故障排除

### 1. 导入错误

```
ImportError: pvporcupine 未安装
```

**解决方案**：
```bash
pip install pvporcupine
```

### 2. Access Key 错误

```
RuntimeError: 初始化 Porcupine 失败: Invalid access key
```

**解决方案**：
- 检查 `PORCUPINE_ACCESS_KEY` 是否正确
- 确认密钥未过期
- 从 [Picovoice Console](https://console.picovoice.ai/) 重新生成

### 3. 唤醒词未检测到

**可能原因**：
- 灵敏度设置过低
- 环境噪音过大
- 发音不标准
- 麦克风音量过低

**解决方案**：
- 提高灵敏度：`WAKE_WORD_SENSITIVITIES=0.6`
- 测试麦克风：`python -m my_openai_robot --test-microphone`
- 尝试不同的唤醒词

### 4. 误触发率高

**解决方案**：
- 降低灵敏度：`WAKE_WORD_SENSITIVITIES=0.4`
- 选择更独特的唤醒词
- 改善录音环境（减少背景噪音）

### 5. 音频缓冲区溢出

```
⚠️  音频缓冲区溢出
```

**解决方案**：
- 关闭其他占用音频设备的程序
- 指定音频设备：`--input-device <ID>`
- 检查系统音频设置

## 📊 性能优化

### CPU 使用率

Porcupine 针对实时处理优化，CPU 使用率很低（<3%）。

### 内存占用

- 单个唤醒词：~1-2 MB
- 多个唤醒词：线性增长

### 延迟

- 检测延迟：< 100 ms
- 总响应时间：取决于网络和 Azure API

## 🔒 隐私与安全

- ✅ 唤醒词检测完全在本地运行
- ✅ 只有检测到唤醒词后才会录音并上传到云端
- ✅ 不会持续上传音频数据
- ✅ Access Key 仅用于激活本地模型

## 💡 最佳实践

1. **选择合适的唤醒词**
   - 选择发音清晰、不易混淆的词
   - 避免日常对话中常见的词
   - 推荐：jarvis, computer, hey google

2. **调整灵敏度**
   - 先使用默认值 0.5
   - 根据实际效果微调
   - 不同环境可能需要不同设置

3. **结合 VAD 使用**
   ```bash
   python -m my_openai_robot --wake-word --use-vad --vad-silence 2.0
   ```

4. **配置儿童模式**
   ```bash
   CHILD_MODE=true
   ENABLE_WAKE_WORD=true
   ```

## 🌟 使用场景

- 🏠 **智能家居助手**：语音控制家居设备
- 👶 **儿童陪伴**：结合儿童安全模式
- 🎓 **学习助手**：免提语音查询
- 💻 **开发助手**：编程时的语音助手
- ♿ **无障碍辅助**：帮助视障或行动不便用户

## 📚 参考资料

- [Picovoice 官方文档](https://picovoice.ai/docs/)
- [Porcupine GitHub](https://github.com/Picovoice/porcupine)
- [自定义唤醒词训练](https://console.picovoice.ai/)
