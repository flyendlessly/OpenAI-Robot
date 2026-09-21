"""Configuration helpers for the Azure OpenAI voice assistant."""
# 核心配置模块：统一加载 Azure OpenAI / 语音 / 计费参数
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from dotenv import dotenv_values
from pydantic import BaseModel, Field


def _bool_from_env(value: Any, default: bool = True) -> bool:
    """将环境变量转换为布尔值，支持 yes/no/true/false 等字符串"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class AzureSettings(BaseModel):
    """Azure OpenAI 服务端点及模型配置"""
    endpoint: str = Field(..., description="Azure OpenAI endpoint URL")
    api_key: str = Field(..., description="Azure OpenAI API key")
    api_version: str = Field(default="2024-02-15-preview")
    deployment: str = Field(..., description="Azure OpenAI deployment name")


class OpenAISettings(BaseModel):
    """OpenAI 官方服务及模型配置"""
    api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    model: str = Field(default="gpt-4o", description="OpenAI model name")
    base_url: Optional[str] = Field(default=None, description="OpenAI Base URL (可选，如中转或代理地址)")


class SpeechSettings(BaseModel):
    """语音识别/合成相关配置"""
    use_azure_speech: bool = True
    speech_key: Optional[str] = None
    speech_region: Optional[str] = None
    stt_endpoint: Optional[str] = None
    tts_endpoint: Optional[str] = None
    stt_language: str = Field(default="zh-CN")
    voice_name: str = Field(default="zh-CN-XiaoxiaoNeural")
    sample_rate: int = Field(default=16000)


class BillingSettings(BaseModel):
    """资源计费监控配置"""
    enabled: bool = Field(default=True, description="是否启用本地计费追踪")
    provider: str = Field(default="sqlite", description="计费插件名称，如 sqlite/json/remote")
    monthly_budget_usd: float = Field(default=150.0)
    warn_ratio: float = Field(default=0.9, description="Trigger warning at 90% budget")
    storage_path: Path = Field(default=Path("data/billing.db"))
    # LLM 费用（以百万 token 为标准单位，符合主流云厂商定价规范）
    prompt_cost_per_1m: float = Field(
        default=0.15, description="美元/百万提示 token (如 gpt-4o-mini 为 $0.15/1M, gpt-4o 为 $2.50/1M)"
    )
    completion_cost_per_1m: float = Field(
        default=0.60, description="美元/百万回答 token (如 gpt-4o-mini 为 $0.60/1M, gpt-4o 为 $10.00/1M)"
    )
    # Azure Speech 费用
    stt_cost_per_hour: float = Field(
        default=1.0, description="语音转文字费用（美元/小时），标准版 $1.0，神经版 $2.5"
    )
    tts_cost_per_million_chars: float = Field(
        default=16.0, description="文字转语音费用（美元/百万字符），标准版 $4.0，神经版 $16.0"
    )

    @property
    def prompt_cost_per_1k(self) -> float:
        return self.prompt_cost_per_1m / 1000.0

    @property
    def completion_cost_per_1k(self) -> float:
        return self.completion_cost_per_1m / 1000.0


class WakeWordSettings(BaseModel):
    """唤醒词检测配置 (Sherpa-ONNX 开源离线)"""
    model_config = {"protected_namespaces": ()}  # 允许 model_ 前缀的字段名

    enabled: bool = Field(default=False, description="是否启用唤醒词检测")
    backend: str = Field(
        default="sherpa-onnx",
        description="唤醒词引擎后端: sherpa-onnx (完全离线开源)"
    )
    keywords: List[str] = Field(
        default=["你好小智", "小智小智"],
        description="唤醒词列表。原生支持自定义中文/拼音词"
    )
    # Sherpa-ONNX 配置
    model_dir: Path = Field(
        default=Path("data/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"),
        description="Sherpa-ONNX KWS 唤醒词模型目录"
    )
    keywords_file: Optional[Path] = Field(
        default=None,
        description="Sherpa-ONNX 自定义关键词文件路径（未指定时自动根据 keywords 生成拼音音素）"
    )
    keywords_score: float = Field(
        default=1.5,
        description="Sherpa-ONNX 唤醒词评分增强系数（越大越容易触发）"
    )
    keywords_threshold: float = Field(
        default=0.25,
        description="Sherpa-ONNX 唤醒概率阈值（越小越灵敏，范围 0.0-1.0）"
    )
    num_threads: int = Field(
        default=1,
        description="Sherpa-ONNX ONNX 推理计算线程数"
    )


class ChildSafetySettings(BaseModel):
    """儿童内容安全保护配置（企业级三层防护）"""
    enabled: bool = Field(default=False, description="是否启用儿童安全模式")
    filter_level: str = Field(
        default="strict",
        description="过滤级别: low/medium/strict"
    )
    use_local_blacklist: bool = Field(
        default=True,
        description="启用本地关键词黑名单预过滤"
    )
    blacklist_path: Path = Field(
        default=Path("data/blacklist.txt"),
        description="本地敏感词库文件路径"
    )
    child_system_prompt: str = Field(
        default="你是一个面向 6-12 岁儿童的智能助手，名叫小智。请使用简单、友好的语言，绝对不能涉及暴力、血腥、色情、恐怖、脏话等内容。如果遇到不适合的问题，温和地引导：'这个问题太复杂了，我们聊点开心的吧！'鼓励好奇心、学习和创造力。",
        description="儿童模式的系统提示词"
    )
    log_all_conversations: bool = Field(
        default=True,
        description="记录所有对话供家长审查"
    )
    conversation_log_path: Path = Field(
        default=Path("data/conversation_logs"),
        description="对话日志存储目录"
    )
    enable_azure_content_filter: bool = Field(
        default=True,
        description="启用 Azure 内容过滤器检查"
    )
    block_on_filter_trigger: bool = Field(
        default=True,
        description="检测到违规内容时是否直接拦截"
    )
    safe_response_template: str = Field(
        default="抱歉，这个话题不太适合我们讨论。我们可以聊聊{suggestion}吗？",
        description="触发过滤时的安全回复模板"
    )
    safe_topics: list[str] = Field(
        default_factory=lambda: ["科学知识", "有趣的故事", "数学游戏", "大自然"],
        description="推荐的安全话题列表"
    )


class WebSearchSettings(BaseModel):
    """联网搜索配置 (Function / Tool Calling)"""
    enabled: bool = Field(default=False, description="是否开启联网搜索能力")
    provider: str = Field(default="duckduckgo", description="搜索引擎提供者: duckduckgo, tavily, bing")
    max_results: int = Field(default=3, description="单次搜索返回的最大条数")
    api_key: Optional[str] = Field(default=None, description="搜索服务 API Key（Tavily 或 Bing 必需，DuckDuckGo 无需）")
    timeout: float = Field(default=10.0, description="搜索请求超时时间（秒）")


class RetrySettings(BaseModel):
    """网络请求重试与韧性配置"""
    enabled: bool = Field(default=True, description="是否启用网络异常自动重试")
    max_retries: int = Field(default=3, ge=0, le=10, description="最大重试次数")
    initial_delay: float = Field(default=0.5, ge=0.0, description="初始重试间隔（秒）")
    max_delay: float = Field(default=5.0, ge=0.1, description="最大重试间隔上限（秒）")
    backoff_factor: float = Field(default=2.0, ge=1.0, description="退避指数乘数")
    jitter: bool = Field(default=True, description="是否启用随机抖动以防惊群效应")


class AppConfig(BaseModel):
    """聚合所有子配置，并负责从环境加载"""
    azure: AzureSettings
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    responses_provider: str = Field(default="azure", description="Responses API 默认后端提供者: azure 或 openai")
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    billing: BillingSettings = Field(default_factory=BillingSettings)
    wake_word: WakeWordSettings = Field(default_factory=WakeWordSettings)
    child_safety: ChildSafetySettings = Field(default_factory=ChildSafetySettings)
    web_search: WebSearchSettings = Field(default_factory=WebSearchSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "AppConfig":
        """Load configuration from environment variables or .env file."""
        env_data: Dict[str, Any] = {}
        if env_file and Path(env_file).exists():
            # 先读取 .env 文件（便于本地开发，显式指定 utf-8）
            env_data.update(dotenv_values(env_file, encoding="utf-8"))
        # 再用系统环境变量覆盖，方便容器/部署环境注入
        env_data.update({key: value for key, value in os.environ.items() if key.startswith("AZURE_")})
        env_data.update({
            "RESPONSES_PROVIDER": os.environ.get("RESPONSES_PROVIDER", env_data.get("RESPONSES_PROVIDER")),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", env_data.get("OPENAI_API_KEY")),
            "OPENAI_MODEL": os.environ.get("OPENAI_MODEL", env_data.get("OPENAI_MODEL")),
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", env_data.get("OPENAI_BASE_URL")),
            "MONTHLY_BUDGET_USD": os.environ.get("MONTHLY_BUDGET_USD", env_data.get("MONTHLY_BUDGET_USD")),
            "BUDGET_WARN_RATIO": os.environ.get("BUDGET_WARN_RATIO", env_data.get("BUDGET_WARN_RATIO")),
            "BILLING_DB_PATH": os.environ.get("BILLING_DB_PATH", env_data.get("BILLING_DB_PATH")),
            "PROMPT_COST_PER_1M": os.environ.get("PROMPT_COST_PER_1M", env_data.get("PROMPT_COST_PER_1M")),
            "COMPLETION_COST_PER_1M": os.environ.get(
                "COMPLETION_COST_PER_1M", env_data.get("COMPLETION_COST_PER_1M")
            ),
            "PROMPT_COST_PER_1K": os.environ.get("PROMPT_COST_PER_1K", env_data.get("PROMPT_COST_PER_1K")),
            "COMPLETION_COST_PER_1K": os.environ.get(
                "COMPLETION_COST_PER_1K", env_data.get("COMPLETION_COST_PER_1K")
            ),
            "ENABLE_BILLING": os.environ.get("ENABLE_BILLING", env_data.get("ENABLE_BILLING")),
            "BILLING_PROVIDER": os.environ.get("BILLING_PROVIDER", env_data.get("BILLING_PROVIDER")),
            # 唤醒词配置
            "ENABLE_WAKE_WORD": os.environ.get("ENABLE_WAKE_WORD", env_data.get("ENABLE_WAKE_WORD")),
            "WAKE_WORD_BACKEND": os.environ.get("WAKE_WORD_BACKEND", env_data.get("WAKE_WORD_BACKEND")),
            "WAKE_WORD_KEYWORDS": os.environ.get("WAKE_WORD_KEYWORDS", env_data.get("WAKE_WORD_KEYWORDS")),
            "WAKE_WORD_MODEL_DIR": os.environ.get("WAKE_WORD_MODEL_DIR", env_data.get("WAKE_WORD_MODEL_DIR")),
            "WAKE_WORD_SCORE": os.environ.get("WAKE_WORD_SCORE", env_data.get("WAKE_WORD_SCORE")),
            "WAKE_WORD_THRESHOLD": os.environ.get("WAKE_WORD_THRESHOLD", env_data.get("WAKE_WORD_THRESHOLD")),
            "WAKE_WORD_NUM_THREADS": os.environ.get("WAKE_WORD_NUM_THREADS", env_data.get("WAKE_WORD_NUM_THREADS")),
            # 儿童安全模式配置
            "CHILD_MODE": os.environ.get("CHILD_MODE", env_data.get("CHILD_MODE")),
            "CONTENT_FILTER_LEVEL": os.environ.get("CONTENT_FILTER_LEVEL", env_data.get("CONTENT_FILTER_LEVEL")),
            "USE_LOCAL_BLACKLIST": os.environ.get("USE_LOCAL_BLACKLIST", env_data.get("USE_LOCAL_BLACKLIST")),
            "BLACKLIST_PATH": os.environ.get("BLACKLIST_PATH", env_data.get("BLACKLIST_PATH")),
            "LOG_ALL_CONVERSATIONS": os.environ.get("LOG_ALL_CONVERSATIONS", env_data.get("LOG_ALL_CONVERSATIONS")),
            "CONVERSATION_LOG_PATH": os.environ.get("CONVERSATION_LOG_PATH", env_data.get("CONVERSATION_LOG_PATH")),
            "CHILD_SYSTEM_PROMPT": os.environ.get("CHILD_SYSTEM_PROMPT", env_data.get("CHILD_SYSTEM_PROMPT")),
            # 联网搜索配置
            "ENABLE_WEB_SEARCH": os.environ.get("ENABLE_WEB_SEARCH", env_data.get("ENABLE_WEB_SEARCH")),
            "WEB_SEARCH_PROVIDER": os.environ.get("WEB_SEARCH_PROVIDER", env_data.get("WEB_SEARCH_PROVIDER")),
            "WEB_SEARCH_MAX_RESULTS": os.environ.get("WEB_SEARCH_MAX_RESULTS", env_data.get("WEB_SEARCH_MAX_RESULTS")),
            "WEB_SEARCH_API_KEY": os.environ.get("WEB_SEARCH_API_KEY", env_data.get("WEB_SEARCH_API_KEY")),
            "WEB_SEARCH_TIMEOUT": os.environ.get("WEB_SEARCH_TIMEOUT", env_data.get("WEB_SEARCH_TIMEOUT")),
        })
        azure = AzureSettings(
            endpoint=env_data.get("AZURE_OPENAI_ENDPOINT", "https://openaitest202601.openai.azure.com/"),
            api_key=env_data.get("AZURE_OPENAI_API_KEY", ""),
            api_version=env_data.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            deployment=env_data.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        )
        speech = SpeechSettings(
            speech_key=env_data.get("AZURE_SPEECH_KEY"),
            speech_region=env_data.get("AZURE_SPEECH_REGION"),
            stt_endpoint=env_data.get("AZURE_SPEECH_STT_ENDPOINT"),
            tts_endpoint=env_data.get("AZURE_SPEECH_TTS_ENDPOINT"),
            stt_language=env_data.get("AZURE_SPEECH_STT_LANGUAGE", "zh-CN"),
            voice_name=env_data.get("AZURE_SPEECH_VOICE", "zh-CN-XiaoxiaoNeural"),
        )
        # 解析 LLM 单价配置（优先使用 PROMPT_COST_PER_1M，兼顾 PROMPT_COST_PER_1K）
        prompt_cost_1m_env = env_data.get("PROMPT_COST_PER_1M")
        prompt_cost_1k_env = env_data.get("PROMPT_COST_PER_1K")
        if prompt_cost_1m_env is not None and str(prompt_cost_1m_env).strip():
            prompt_cost_1m = float(prompt_cost_1m_env)
        elif prompt_cost_1k_env is not None and str(prompt_cost_1k_env).strip():
            val = float(prompt_cost_1k_env)
            prompt_cost_1m = val if val >= 0.01 else val * 1000.0
        else:
            prompt_cost_1m = 0.15

        completion_cost_1m_env = env_data.get("COMPLETION_COST_PER_1M")
        completion_cost_1k_env = env_data.get("COMPLETION_COST_PER_1K")
        if completion_cost_1m_env is not None and str(completion_cost_1m_env).strip():
            completion_cost_1m = float(completion_cost_1m_env)
        elif completion_cost_1k_env is not None and str(completion_cost_1k_env).strip():
            val = float(completion_cost_1k_env)
            completion_cost_1m = val if val >= 0.01 else val * 1000.0
        else:
            completion_cost_1m = 0.60

        billing = BillingSettings(
            enabled=_bool_from_env(env_data.get("ENABLE_BILLING", True)),
            provider=(env_data.get("BILLING_PROVIDER") or "sqlite"),
            monthly_budget_usd=float(env_data.get("MONTHLY_BUDGET_USD", 150)),
            warn_ratio=float(env_data.get("BUDGET_WARN_RATIO", 0.9)),
            storage_path=Path(env_data.get("BILLING_DB_PATH", "data/billing.db")),
            prompt_cost_per_1m=prompt_cost_1m,
            completion_cost_per_1m=completion_cost_1m,
            stt_cost_per_hour=float(env_data.get("STT_COST_PER_HOUR", 1.0)),
            tts_cost_per_million_chars=float(env_data.get("TTS_COST_PER_MILLION_CHARS", 16.0)),
        )
        # 解析唤醒词配置
        backend = (env_data.get("WAKE_WORD_BACKEND") or "sherpa-onnx").lower().strip()
        default_keywords = "芝麻开门,你好小智,小智小智"
        keywords_str = env_data.get("WAKE_WORD_KEYWORDS", default_keywords)
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

        model_dir_str = env_data.get("WAKE_WORD_MODEL_DIR")
        model_dir = (
            Path(model_dir_str)
            if model_dir_str
            else Path("data/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01")
        )

        keywords_file_str = env_data.get("WAKE_WORD_KEYWORDS_FILE")
        keywords_file = Path(keywords_file_str) if keywords_file_str else None

        score_val = env_data.get("WAKE_WORD_SCORE")
        keywords_score = float(score_val) if score_val is not None and str(score_val).strip() else 1.5

        thresh_val = env_data.get("WAKE_WORD_THRESHOLD")
        keywords_threshold = float(thresh_val) if thresh_val is not None and str(thresh_val).strip() else 0.25

        threads_val = env_data.get("WAKE_WORD_NUM_THREADS")
        num_threads = int(threads_val) if threads_val is not None and str(threads_val).strip() else 1

        wake_word = WakeWordSettings(
            enabled=_bool_from_env(env_data.get("ENABLE_WAKE_WORD", False), default=False),
            backend=backend,
            keywords=keywords,
            model_dir=model_dir,
            keywords_file=keywords_file,
            keywords_score=keywords_score,
            keywords_threshold=keywords_threshold,
            num_threads=num_threads,
        )
        child_safety = ChildSafetySettings(
            enabled=_bool_from_env(env_data.get("CHILD_MODE", False), default=False),
            filter_level=env_data.get("CONTENT_FILTER_LEVEL") or "strict",
            use_local_blacklist=_bool_from_env(env_data.get("USE_LOCAL_BLACKLIST"), default=True),
            blacklist_path=Path(env_data.get("BLACKLIST_PATH") or "data/blacklist.txt"),
            log_all_conversations=_bool_from_env(env_data.get("LOG_ALL_CONVERSATIONS"), default=True),
            conversation_log_path=Path(env_data.get("CONVERSATION_LOG_PATH") or "data/conversation_logs"),
            child_system_prompt=env_data.get(
                "CHILD_SYSTEM_PROMPT"
            ) or "你是一个面向 6-12 岁儿童的智能助手，名叫小智。请使用简单、友好的语言，绝对不能涉及暴力、血腥、色情、恐怖、脏话等内容。如果遇到不适合的问题，温和地引导：'这个问题太复杂了，我们聊点开心的吧！'鼓励好奇心、学习和创造力。",
        )
        max_results_env = env_data.get("WEB_SEARCH_MAX_RESULTS")
        max_results = int(max_results_env) if max_results_env is not None and str(max_results_env).strip() else 3

        timeout_env = env_data.get("WEB_SEARCH_TIMEOUT")
        timeout = float(timeout_env) if timeout_env is not None and str(timeout_env).strip() else 10.0

        web_search = WebSearchSettings(
            enabled=_bool_from_env(env_data.get("ENABLE_WEB_SEARCH", False), default=False),
            provider=env_data.get("WEB_SEARCH_PROVIDER") or "duckduckgo",
            max_results=max_results,
            api_key=env_data.get("WEB_SEARCH_API_KEY"),
            timeout=timeout,
        )
        openai = OpenAISettings(
            api_key=env_data.get("OPENAI_API_KEY") or None,
            model=env_data.get("OPENAI_MODEL") or "gpt-4o",
            base_url=env_data.get("OPENAI_BASE_URL") or None,
        )
        responses_provider = env_data.get("RESPONSES_PROVIDER") or "azure"

        retry_max_retries_env = env_data.get("RETRY_MAX_RETRIES")
        max_retries = int(retry_max_retries_env) if retry_max_retries_env is not None and str(retry_max_retries_env).strip() else 3

        retry_initial_delay_env = env_data.get("RETRY_INITIAL_DELAY")
        initial_delay = float(retry_initial_delay_env) if retry_initial_delay_env is not None and str(retry_initial_delay_env).strip() else 0.5

        retry_max_delay_env = env_data.get("RETRY_MAX_DELAY")
        max_delay = float(retry_max_delay_env) if retry_max_delay_env is not None and str(retry_max_delay_env).strip() else 5.0

        retry_backoff_factor_env = env_data.get("RETRY_BACKOFF_FACTOR")
        backoff_factor = float(retry_backoff_factor_env) if retry_backoff_factor_env is not None and str(retry_backoff_factor_env).strip() else 2.0

        retry = RetrySettings(
            enabled=_bool_from_env(env_data.get("RETRY_ENABLED"), default=True),
            max_retries=max_retries,
            initial_delay=initial_delay,
            max_delay=max_delay,
            backoff_factor=backoff_factor,
            jitter=_bool_from_env(env_data.get("RETRY_JITTER"), default=True),
        )

        return cls(
            azure=azure,
            openai=openai,
            responses_provider=responses_provider,
            speech=speech,
            billing=billing,
            wake_word=wake_word,
            child_safety=child_safety,
            web_search=web_search,
            retry=retry,
        )
