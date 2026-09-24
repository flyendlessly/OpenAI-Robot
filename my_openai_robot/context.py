"""Application context and runtime dependency container (SSOT for runtime state)."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .audio_io import (
    AudioSettings,
    SoundDeviceMicrophone,
    SoundDeviceSpeaker,
    SoundDeviceUnavailable,
)
from .billing_tracker import BillingTrackerProtocol, create_billing_tracker
from .child_safety import ChildSafetyFilter
from .config import AppConfig
from .conversation_manager import ConversationManager
from .conversation_store import ConversationStore
from .llm_client import AzureLLMClient, LLMClientProtocol, LLMResponse
from .logger import get_logger
from .responses_api import ResponsesAPIClientAdapter, get_responses_provider
from .speech_service import SpeechService, create_speech_service
from .web_search import create_search_engine

logger = get_logger("context")


@dataclass
class AppContext:
    """运行时上下文容器：集中持有配置、LLM 客户端、语音服务、数据库与硬件设备句柄。"""

    config: AppConfig
    args: argparse.Namespace
    llm_client: Union[AzureLLMClient, LLMClientProtocol]
    speech_service: Optional[SpeechService] = None
    conversation_store: Optional[ConversationStore] = None
    billing_tracker: Optional[BillingTrackerProtocol] = None
    safety_filter: Optional[ChildSafetyFilter] = None
    microphone: Optional[SoundDeviceMicrophone] = None
    speaker: Optional[SoundDeviceSpeaker] = None
    conversation_manager: Optional[ConversationManager] = None

    def log_usage(
        self,
        response: Optional[LLMResponse],
        *,
        stt_duration: float = 0.0,
        tts_characters: int = 0,
    ) -> None:
        """记录 Token / 语音用量并在控制台打印费用摘要"""
        usage_data: dict[str, Any] = {}
        if response and response.usage:
            usage_data.update(response.usage)
            print("--- 用量 ---")
            print(json.dumps(response.usage, ensure_ascii=False, indent=2))

        if response and response.searched:
            print(f"[联网搜索] 触发关键词: {', '.join(response.search_queries)}")

        if stt_duration > 0:
            usage_data["stt_duration_seconds"] = stt_duration
        if tts_characters > 0:
            usage_data["tts_characters"] = tts_characters

        if not usage_data:
            return

        if self.billing_tracker:
            usage_record = self.billing_tracker.record_usage(usage_data)
            monthly_cost = self.billing_tracker.get_monthly_cost()
            print(f"本次预估费用: ${usage_record.cost_usd:.6f}")
            print(
                f"本月累计费用: ${monthly_cost:.4f} / ${self.billing_tracker.settings.monthly_budget_usd:.2f}"
            )
            if self.billing_tracker.should_warn(monthly_cost):
                print("⚠ 达到预算告警阈值，请关注使用量！")

    def log_turn(
        self,
        *,
        user_input: str,
        assistant_response: str,
        model: Optional[str],
        mode: str,
        usage_tokens: int = 0,
    ) -> None:
        """记录一轮对话到持久化存储"""
        if self.conversation_store:
            self.conversation_store.log(
                user_input=user_input,
                assistant_response=assistant_response,
                model=model,
                mode=mode,
                usage_tokens=usage_tokens,
            )


def create_app_context(config: AppConfig, args: argparse.Namespace) -> AppContext:
    """依据配置与命令行参数组装运行时上下文 (IoC 容器构建)"""

    # 1. 处理 Web Search 与 Provider 覆盖
    if getattr(args, "web_search", None) is not None:
        config.web_search.enabled = args.web_search
    if getattr(args, "search_provider", None):
        config.web_search.provider = args.search_provider
    if getattr(args, "provider", None):
        config.responses_provider = args.provider

    target_provider = (config.responses_provider or "azure").strip().lower()

    if target_provider in ("azure", "openai"):
        search_engine = None
        search_info = f"native (Responses API built-in: {config.web_search.enabled})"
    else:
        search_engine = create_search_engine(config.web_search)
        search_info = f"{config.web_search.provider} (enabled: {config.web_search.enabled})"

    logger.info(
        "Config loaded: provider=%s, deployment/model=%s, billing=%s, web_search=%s",
        target_provider,
        config.openai.model if target_provider == "openai" else config.azure.deployment,
        config.billing.enabled,
        search_info,
    )

    # 2. 初始化 LLM 客户端
    if target_provider in ("azure", "openai"):
        logger.info(
            "Initializing Responses API provider: target=%s, native_web_search=%s",
            target_provider,
            config.web_search.enabled,
        )
        provider = get_responses_provider(config, provider=target_provider)
        client = ResponsesAPIClientAdapter(provider, enable_web_search=config.web_search.enabled)
    else:
        logger.info(
            "Initializing legacy Azure Chat client: endpoint=%s, deployment=%s",
            config.azure.endpoint,
            config.azure.deployment,
        )
        client = AzureLLMClient(
            endpoint=config.azure.endpoint,
            api_key=config.azure.api_key,
            deployment=config.azure.deployment,
            api_version=config.azure.api_version,
            search_engine=search_engine,
            retry_settings=config.retry,
        )

    # 3. 计费追踪与对话存储
    tracker: Optional[BillingTrackerProtocol] = None
    if config.billing.enabled:
        tracker = create_billing_tracker(config.billing)
        if tracker is None:
            logger.warning("计费插件 '%s' 未注册，跳过费用记录。", config.billing.provider)
    else:
        logger.info("计费追踪已禁用，可通过 ENABLE_BILLING 配置重新开启。")

    store = ConversationStore(config.billing.storage_path)

    # 4. 语音服务与硬件设备 (按需构建)
    speech_service = create_speech_service(config.speech, retry_settings=config.retry)
    microphone: Optional[SoundDeviceMicrophone] = None
    speaker: Optional[SoundDeviceSpeaker] = None
    safety_filter: Optional[ChildSafetyFilter] = None
    conversation_mgr: Optional[ConversationManager] = None

    needs_audio = getattr(args, "voice_turn", False) or getattr(args, "wake_word", False)
    if needs_audio:
        if speech_service is None:
            raise SystemExit(
                "未启用 Azure Speech，无法执行语音对话。\n"
                "请在 .env 中设置 AZURE_SPEECH_KEY 和 AZURE_SPEECH_REGION（或 STT/TTS endpoints）"
            )
        try:
            audio_settings = AudioSettings(sample_rate=config.speech.sample_rate)
            microphone = SoundDeviceMicrophone(audio_settings, device=getattr(args, "input_device", None))
            speaker = SoundDeviceSpeaker(device=getattr(args, "output_device", None))

            if getattr(args, "input_device", None) is None or getattr(args, "output_device", None) is None:
                print("\n提示: 使用 --list-devices 查看所有可用设备")
                print("      使用 --test-microphone 测试麦克风")
                print("      使用 --input-device <ID> 和 --output-device <ID> 指定设备\n")
        except SoundDeviceUnavailable as exc:
            raise SystemExit(f"麦克风/扬声器不可用: {exc}")

        # 儿童安全检查
        if config.child_safety.enabled:
            checkmark = "✓"
            crossmark = "✗"
            print("\n👶 儿童安全模式已启用")
            print(f"   过滤级别: {config.child_safety.filter_level}")
            print(f"   本地黑名单: {checkmark if config.child_safety.use_local_blacklist else crossmark}")
            print(f"   Azure 过滤: {checkmark if config.child_safety.enable_azure_content_filter else crossmark}")
            print(f"   对话日志: {checkmark if config.child_safety.log_all_conversations else crossmark}\n")
            safety_filter = ChildSafetyFilter(config.child_safety)
            if not getattr(args, "system_prompt", None):
                args.system_prompt = config.child_safety.child_system_prompt

        conversation_mgr = ConversationManager(
            llm_client=client,
            speech_service=speech_service,
            system_prompt=getattr(args, "system_prompt", None),
            safety_filter=safety_filter,
        )

    return AppContext(
        config=config,
        args=args,
        llm_client=client,
        speech_service=speech_service,
        conversation_store=store,
        billing_tracker=tracker,
        safety_filter=safety_filter,
        microphone=microphone,
        speaker=speaker,
        conversation_manager=conversation_mgr,
    )
