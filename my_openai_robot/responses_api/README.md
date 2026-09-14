# Responses API 模块说明

`my_openai_robot/responses_api/` 是专为 OpenAI 新一代 **Responses API** (`client.responses.create`) 设计的模块化封装，支持在 **Azure OpenAI** 与 **OpenAI 官方服务** 之间一键无缝切换。

---

## 🌟 核心特性

1. **一键无缝切换**：通过 `.env` 中的 `RESPONSES_PROVIDER=azure` 或 `openai`，或在工厂中动态指定提供者即可完成切换。
2. **统一响应对象 (`ResponseResult`)**：屏蔽不同平台返回结构的细微差异，统一提取回复文本、Token 消耗、搜索查询词等关键元数据。
3. **原生内置 Web 搜索**：支持声明 `enable_web_search=True`，直接触发模型内置的 `web_search_preview` 工具，免去复杂的本地搜索引擎接入。
4. **企业级网络适应**：默认绕过本地系统代理冲突（`trust_env=False`）。

---

## 📁 目录结构

```text
my_openai_robot/responses_api/
├── README.md               # 模块专属说明与开发指南
├── __init__.py             # 统一导出
├── base.py                 # 抽象基类 BaseResponsesProvider 与数据结构 ResponseResult
├── azure_provider.py       # Azure OpenAI Responses API 实现
├── openai_provider.py      # OpenAI 官方 Responses API 实现
└── factory.py              # 工厂方法 get_responses_provider
```

---

## ⚙️ 配置说明

在根目录的 `.env` 文件中配置以下参数：

```env
# 核心切换开关: 可选 "azure" 或 "openai" (默认为 azure)
RESPONSES_PROVIDER=azure

# 1. Azure OpenAI 配置
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your_azure_key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2025-03-01-preview

# 2. OpenAI 官方配置
OPENAI_API_KEY=sk-your_openai_api_key
OPENAI_MODEL=gpt-4o
# OPENAI_BASE_URL=https://api.openai.com/v1 (可选自定义网关)
```

---

## 🚀 快速上手与使用示例

### 1. 使用工厂方法自动初始化

```python
from my_openai_robot.config import AppConfig
from my_openai_robot.responses_api import get_responses_provider

# 加载配置
config = AppConfig.from_env()

# 根据 .env 中的 RESPONSES_PROVIDER 自动获取对应 Provider
provider = get_responses_provider(config)

# 基础调用
result = provider.create_response(
    input_text="你好，请做个自我介绍！",
    instructions="你是一个聪明可爱的机器人助手。"
)

print(f"回复内容: {result.text}")
print(f"Token 消耗: {result.usage}")
```

### 2. 启用原生 Web 搜索

```python
result = provider.create_response(
    input_text="今天北京的天气怎么样？",
    enable_web_search=True
)

print(f"回复内容: {result.text}")
if result.searched:
    print(f"触发的搜索词: {result.search_queries}")
```

### 3. 代码中动态指定后端

```python
# 临时强制使用 OpenAI 官方后端
openai_provider = get_responses_provider(config, provider="openai")

# 临时强制使用 Azure 后端
azure_provider = get_responses_provider(config, provider="azure")
```
