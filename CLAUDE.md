# Azure OpenAI 语音助手 (my-openai-robot) - Claude Code 约束

请遵循 `AGENTS.md` 中定义的架构规范、语义路由表与研发铁律：
1. **语义路由定位**：定位功能或修改代码时，优先查阅 `AGENTS.md` 对应的模块文件，不要全局遍历或读取无关上下文。
2. **忽略噪音目录**：绝不读取或扫描 `.venv/`、`data/`、`*.wav`、`*.db` 等非代码文件。
3. **配置与安全**：配置修改遵循 `my_openai_robot/config.py`，不得硬编码密钥。
