"""Configuration helpers for the Azure OpenAI voice assistant."""
# 核心配置模块：统一加载 Azure OpenAI / 语音 / 计费参数
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

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
    prompt_cost_per_1k: float = Field(
        default=0.15, description="美元/千提示 token，可按部署模型调整"
    )
    completion_cost_per_1k: float = Field(
        default=0.6, description="美元/千回答 token，可按部署模型调整"
    )


class AppConfig(BaseModel):
    """聚合所有子配置，并负责从环境加载"""
    azure: AzureSettings
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    billing: BillingSettings = Field(default_factory=BillingSettings)

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "AppConfig":
        """Load configuration from environment variables or .env file."""
        env_data: Dict[str, Any] = {}
        if env_file and Path(env_file).exists():
            # 先读取 .env 文件（便于本地开发）
            env_data.update(dotenv_values(env_file))
        # 再用系统环境变量覆盖，方便容器/部署环境注入
        env_data.update({key: value for key, value in os.environ.items() if key.startswith("AZURE_")})
        env_data.update({
            "MONTHLY_BUDGET_USD": os.environ.get("MONTHLY_BUDGET_USD", env_data.get("MONTHLY_BUDGET_USD")),
            "BUDGET_WARN_RATIO": os.environ.get("BUDGET_WARN_RATIO", env_data.get("BUDGET_WARN_RATIO")),
            "BILLING_DB_PATH": os.environ.get("BILLING_DB_PATH", env_data.get("BILLING_DB_PATH")),
            "PROMPT_COST_PER_1K": os.environ.get("PROMPT_COST_PER_1K", env_data.get("PROMPT_COST_PER_1K")),
            "COMPLETION_COST_PER_1K": os.environ.get(
                "COMPLETION_COST_PER_1K", env_data.get("COMPLETION_COST_PER_1K")
            ),
            "ENABLE_BILLING": os.environ.get("ENABLE_BILLING", env_data.get("ENABLE_BILLING")),
            "BILLING_PROVIDER": os.environ.get("BILLING_PROVIDER", env_data.get("BILLING_PROVIDER")),
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
        billing = BillingSettings(
            enabled=_bool_from_env(env_data.get("ENABLE_BILLING", True)),
            provider=(env_data.get("BILLING_PROVIDER") or "sqlite"),
            monthly_budget_usd=float(env_data.get("MONTHLY_BUDGET_USD", 150)),
            warn_ratio=float(env_data.get("BUDGET_WARN_RATIO", 0.9)),
            storage_path=Path(env_data.get("BILLING_DB_PATH", "data/billing.db")),
            prompt_cost_per_1k=float(env_data.get("PROMPT_COST_PER_1K", 0.15)),
            completion_cost_per_1k=float(env_data.get("COMPLETION_COST_PER_1K", 0.6)),
        )
        return cls(azure=azure, speech=speech, billing=billing)
