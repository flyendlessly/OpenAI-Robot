# Azure OpenAI 语音助手 (my-openai-robot) - 架构与开发指南

## 1. 语义路由表 (修改功能时直接读取目标文件，严禁全库全局搜索)

| 功能领域 | 核心文件路径 | 依赖技术 / 说明 |
| :--- | :--- | :--- |
| **CLI 入口与运行模式** | `my_openai_robot/__main__.py` | 参数解析 (text/voice/listen/history/billing/search)、主流程调度 |
| **对话状态编排** | `my_openai_robot/conversation_manager.py` | 串联 STT -> LLM -> TTS -> 计费 -> 日志的核心状态机 |
| **唤醒词检测** | `my_openai_robot/wake_word.py` | 基于 Picovoice Porcupine 的低功耗本地唤醒词监听 |
| **音频采集/播放/VAD** | `my_openai_robot/audio_io.py` | 基于 WebRTC VAD 的静音检测与断句录音，sounddevice 音频输出 |
| **语音识别与合成 (STT/TTS)** | `my_openai_robot/speech_service.py` | Azure Cognitive Services Speech SDK 封装 |
| **LLM 交互与 Client** | `my_openai_robot/llm_client.py` | 官方 OpenAI SDK (Azure 适配)、Function Calling / Web Search 调度、Token 累加计费 |
| **联网搜索与工具调用** | `my_openai_robot/web_search.py` | DuckDuckGo / Tavily / Bing 搜索服务适配与 Tool Schema 定义 |
| **儿童安全与内容审查** | `my_openai_robot/child_safety.py` | 本地敏感词黑名单 + System Prompt 约束 + Azure 过滤器三层防御 |
| **计费与预算控制** | `my_openai_robot/billing_tracker.py` | SQLite 记录 Token 与 Speech 费用，月度预算监控与预警 |
| **对话持久化存储** | `my_openai_robot/conversation_store.py` | SQLite 存储问答记录、Token 消耗、元数据 |
| **配置验证与环境变量** | `my_openai_robot/config.py` | Pydantic Settings 配置映射与强类型校验 |
| **统一日志体系** | `my_openai_robot/logger.py` | 结构化日志 (Console + File 日志输出) |
| **数据库版本迁移** | `migrations/` | 数据库初始与增量迁移脚本 |

---

## 2. 研发铁律 (Token & 效率控制)

1. **精准操作，拒绝全局盲搜**：
   - 绝不要全库扫描或读取 `.venv/`、`data/`、`*.wav`、`*.db` 等大文件/二进制文件。
   - 查阅业务代码前，先通过上方路由表定位 1~2 个目标文件。
2. **配置演进规范**：
   - 新增配置项必须在 `my_openai_robot/config.py` 定义并提供默认值及校验逻辑。
   - 同步更新 `.env.example`，严禁将真实 Key 写入代码或提交到 git。
3. **音频/阻塞调用规范**：
   - 音频录制与播放涉及系统硬件设备及阻塞 I/O，注意线程安全与状态重置。
   - 涉及网络调用的模块（LLM / STT / TTS / WebSearch）注意保留并完善异常捕获与降级机制。
4. **代码风格与类型约束**：
   - 全面使用 Python 3.10+ 类型注解 (Type Hints)。
   - 保持 Pydantic 数据验证与日志埋点规范。
