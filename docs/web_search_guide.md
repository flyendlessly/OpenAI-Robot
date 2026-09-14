# 联网搜索（Web Search）使用与配置指南

本项目支持通过标准 **Function / Tool Calling** 为 Azure OpenAI 赋予实时联网搜索能力。

---

## 1. 架构与工作原理

针对 Azure OpenAI 目前的特性，采用行业标准的 **Tool Calling 回传机制**，兼顾稳定兼容性与精确计费：

```
 用户提问 ("今天天气/最新新闻是什么？")
     │
     ▼
 ┌─────────────────────────────────────────────────────────┐
 │ 1. AzureLLMClient.chat(messages, tools=[web_search])    │
 └────────────────────────────┬────────────────────────────┘
                              │ 模型判断需要搜索
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ 2. WebSearchEngine.execute(query="...")                 │
 │    (支持 DuckDuckGo / Tavily / Bing 引擎)                │
 └────────────────────────────┬────────────────────────────┘
                              │ 返回结构化搜索结果
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ 3. 回传 role="tool" 结果给 Azure OpenAI 生成最终回复     │
 └────────────────────────────┬────────────────────────────┘
                              │ 累加各轮次的 Prompt / Completion Tokens
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ 4. BillingTracker 记录准确的 API 费用支出               │
 └─────────────────────────────────────────────────────────┘
```

---

## 2. 快速配置

在 `.env` 文件中配置以下环境变量：

```dotenv
# 启用联网搜索
ENABLE_WEB_SEARCH=true

# 搜索引擎类型（duckduckgo / tavily / bing）
WEB_SEARCH_PROVIDER=duckduckgo

# 搜索服务 API Key（DuckDuckGo 无需填写，Tavily / Bing 必需）
WEB_SEARCH_API_KEY=

# 单次检索最大条数（推荐 3-5 条）
WEB_SEARCH_MAX_RESULTS=3

# 超时时间（秒）
WEB_SEARCH_TIMEOUT=10.0
```

---

## 3. 支持的搜索引擎 (Providers)

| 提供商 | 配置值 | 需要 API Key | 特点与适用场景 |
| :--- | :--- | :--- | :--- |
| **DuckDuckGo** | `duckduckgo` | 否（完全免费） | 开箱即用，支持通过 `duckduckgo_search` 抓取网页摘要并自带 API 降级 |
| **Tavily AI** | `tavily` | 是 | 专为 LLM Agent 优化的高质量搜索，结果干净且上下文相关度高 |
| **Azure Bing** | `bing` | 是 | 微软官方 Bing Web Search API，适合企业级 Azure 订阅集成 |

---

## 4. CLI 调试与运行

```bash
# 1. 开启联网搜索单轮测试
python -m my_openai_robot "介绍一下目前最新的科技热点" --web-search

# 2. 指定搜索引擎提供商
python -m my_openai_robot "微软最新的财报情况" --web-search --search-provider tavily

# 3. 交互式 REPL 模式（默认按 .env 配置加载）
python -m my_openai_robot

# 4. 语音对话模式下使用联网搜索
python -m my_openai_robot --voice-turn --use-vad --web-search
```

---

## 5. Token 计费与预算保护

在触发 Tool Calling 时，系统会自动对：
1. **第一轮交互**（模型分析问题并决定发起 `web_search` 调用）；
2. **第二轮交互**（模型整合搜索结果并组织最终回答）；

所消耗的 `prompt_tokens` 与 `completion_tokens` 进行累加，并如实写入 `data/billing.db` 费用数据库，确保月度预算与告警机制完全准确。
