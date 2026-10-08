# Azure OpenAI 语音助手 (my-openai-robot) - Claude Code 约束

请遵循 `AGENTS.md` 中定义的架构规范、语义路由表与研发铁律：
1. **语义路由定位**：定位功能或修改代码时，优先查阅 `AGENTS.md` 对应的模块文件，不要全局遍历或读取无关上下文。
2. **忽略噪音目录**：绝不读取或扫描 `.venv/`、`data/`、`*.wav`、`*.db` 等非代码文件。
3. **配置与安全**：配置修改遵循 `my_openai_robot/config.py`，不得硬编码密钥。

---

## 架构演进与后续优化路线图 (Architecture Evolution Roadmap)

在后续架构升级与功能迭代时，优先参考以下三项进阶优化方向：

### 1. 并发模型向 AsyncIO 事件循环的融合 (Concurrency & Event Loop)
- **现状分析**：当前核心流控主要基于同步阻塞 + 多线程 (`threading.Thread` + `queue.Queue` + `threading.Event`)。在控制底层声卡 I/O 时运行稳健，但在扩展复杂网络异步 I/O 时略显笨重。
- **优化路径**：
  - 将上层业务流程调度（LLM 调用、WebSearch、多 Agent 协作、状态机）迁移至 `asyncio` 异步事件循环。
  - 声卡录播（sounddevice）等阻塞式硬件 I/O 保留在独立 Worker 线程池中，通过 `asyncio.to_thread` 或专用队列与主事件循环桥接。
- **关联模块**：`my_openai_robot/conversation_manager.py`、`my_openai_robot/streaming/pipeline.py`。

### 2. 端到端全双工实时流接入 (Realtime API & WebRTC)
- **现状分析**：当前采用级联流水线架构：`STT (音频转文字) -> LLM (文本推理) -> TTS (语音合成)`。尽管已实现流式切句并行，但在复杂问答下仍有固定链路耗时。
- **优化路径**：
  - 在 `my_openai_robot/responses_api/` 或新增模块中，探索并预留端到端全双工实时多模态语音协议（如 OpenAI Realtime API / WebSocket 双向音频流）。
  - 支持端到端音频进出，跳过中间文本级联环节，将端到端延迟进一步压缩到日常交谈级（~300ms）。
- **关联模块**：`my_openai_robot/responses_api/`、`my_openai_robot/streaming/`。

### 3. 物理回声消除 (AEC, Acoustic Echo Cancellation)
- **现状分析**：在启用流式播放同时进行 Barge-in（唤醒词实时打断）监听时，如果扬声器音量较大，播放的声音易回灌至麦克风，产生自激或误触发。
- **优化路径**：
  - 软件层面：在 `my_openai_robot/audio_io.py` 采集音频帧送入唤醒词检测前，引入轻量级软件回声消除（如 WebRTC AECM 算法模块）。
  - 硬件层面：在部署文档 `deploy/README.md` 中推荐/适配带硬件 DSP AEC 的麦克风阵列拾音硬件（如 ReSpeaker 阵列板）。
- **关联模块**：`my_openai_robot/audio_io.py`、`my_openai_robot/wake_word.py`、`deploy/README.md`。

