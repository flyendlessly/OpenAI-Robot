"""Entry point for CLI testing."""
# 文本 & 语音 CLI：便于验证 Azure LLM / Speech / 音频链路 / 联网搜索
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List, Optional, Union

from .audio_io import (
    AudioSettings,
    SoundDeviceMicrophone,
    SoundDeviceSpeaker,
    SoundDeviceUnavailable,
    list_audio_devices,
    test_microphone,
)
from .billing_tracker import BillingTrackerProtocol, create_billing_tracker
from .child_safety import ChildSafetyFilter
from .config import AppConfig
from .conversation_manager import ConversationManager
from .conversation_store import ConversationStore
from .llm_client import AzureLLMClient, LLMClientProtocol, LLMResponse, Message
from .logger import get_logger, setup_logging
from .responses_api import ResponsesAPIClientAdapter, get_responses_provider
from .speech_service import create_speech_service
from .wake_word import create_wake_word_detector, list_builtin_keywords
from .web_search import create_search_engine

logger = get_logger("cli")


def build_arg_parser() -> argparse.ArgumentParser:
    # 提供最常用的调试参数，方便快速迭代
    parser = argparse.ArgumentParser(description="Azure OpenAI 语音助手 CLI")
    parser.add_argument("prompt", nargs="?", help="要发送的用户提示；为空则进入交互模式")
    parser.add_argument("--system", default="你是一个乐于助人的中文语音助手。", dest="system_prompt")
    parser.add_argument("--max-tokens", type=int, default=512, dest="max_tokens")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--voice-turn", action="store_true", help="使用麦克风录制一次语音并播放回复")
    parser.add_argument("--record-seconds", type=float, default=5.0, help="单次语音录制时长（秒），使用 VAD 时为最大时长")
    parser.add_argument("--use-vad", action="store_true", help="使用 VAD 自动检测说话开始和结束（推荐）")
    parser.add_argument("--vad-silence", type=float, default=2.0, help="VAD 模式：连续静音多久后停止（秒）")
    parser.add_argument("--vad-aggressiveness", type=int, default=2, choices=[0, 1, 2, 3], help="VAD 灵敏度 0-3，越高越不容易误触发")
    parser.add_argument("--save-reply-audio", help="将 AI 回复语音保存为 WAV 文件")
    parser.add_argument("--stream", action="store_true", default=True, help="启用流式并发流水线（大幅降低语音与文本延迟，默认开启）")
    parser.add_argument("--no-stream", action="store_false", dest="stream", help="禁用流式，使用传统串行模式")
    parser.add_argument("--list-devices", action="store_true", help="列出所有可用音频设备")
    parser.add_argument("--test-microphone", action="store_true", help="测试麦克风是否正常工作")
    parser.add_argument("--input-device", type=int, help="指定输入设备 ID（使用 --list-devices 查看）")
    parser.add_argument("--output-device", type=int, help="指定输出设备 ID（使用 --list-devices 查看）")
    parser.add_argument("--wake-word", action="store_true", help="启用唤醒词监听模式（持续监听，检测到唤醒词后开始对话）")
    parser.add_argument("--list-wake-words", action="store_true", help="列出所有支持的内置唤醒词")
    parser.add_argument("--web-search", action="store_true", default=None, help="启用联网搜索 (覆盖 .env)")
    parser.add_argument("--no-web-search", action="store_false", dest="web_search", help="禁用联网搜索 (覆盖 .env)")
    parser.add_argument("--provider", choices=["azure", "openai", "azure_chat"], help="指定 LLM Provider (覆盖 .env 中的 RESPONSES_PROVIDER)")
    parser.add_argument("--search-provider", choices=["duckduckgo", "tavily", "bing"], help="指定联网搜索引擎")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="日志级别")
    parser.add_argument("--log-file", help="日志输出文件路径（可选）")
    return parser


def _log_usage(
    response: Optional[LLMResponse],
    tracker: Optional[BillingTrackerProtocol],
    *,
    stt_duration: float = 0.0,
    tts_characters: int = 0,
) -> None:
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

    if tracker:
        usage_record = tracker.record_usage(usage_data)
        monthly_cost = tracker.get_monthly_cost()
        print(f"本次预估费用: ${usage_record.cost_usd:.6f}")
        print(f"本月累计费用: ${monthly_cost:.4f} / ${tracker.settings.monthly_budget_usd:.2f}")
        if tracker.should_warn(monthly_cost):
            print("⚠ 达到预算告警阈值，请关注使用量！")


def run_single_turn(
    client: Union[AzureLLMClient, LLMClientProtocol],
    prompt: str,
    *,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    stream: bool = True,
    tracker: Optional[BillingTrackerProtocol] = None,
    store: Optional[ConversationStore] = None,
) -> None:
    # 组装最小对话上下文并调用 LLM
    messages: List[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=prompt),
    ]
    print("--- AI 回复 ---")
    if stream and hasattr(client, "chat_stream"):
        tokens: List[str] = []
        for token in client.chat_stream(messages, max_tokens=max_tokens, temperature=temperature):
            tokens.append(token)
            print(token, end="", flush=True)
        print()
        reply_text = "".join(tokens).strip()
        response = LLMResponse(
            text=reply_text,
            usage={
                "prompt_tokens": len(prompt) * 2,
                "completion_tokens": len(reply_text) * 2,
                "total_tokens": (len(prompt) + len(reply_text)) * 2,
            },
            model=getattr(client, "deployment", getattr(client, "model", "streaming")),
        )
    else:
        response = client.chat(messages, max_tokens=max_tokens, temperature=temperature)
        print(response.text)

    if store:
        store.log(
            user_input=prompt,
            assistant_response=response.text,
            model=response.model,
            mode="text",
            usage_tokens=(response.usage or {}).get("total_tokens", 0),
        )
    _log_usage(response, tracker)


def interactive_loop(
    client: Union[AzureLLMClient, LLMClientProtocol],
    *,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    stream: bool = True,
    tracker: Optional[BillingTrackerProtocol] = None,
    store: Optional[ConversationStore] = None,
) -> None:
    # 简单 REPL，便于连续对话测试（保持上下文）
    print(f"进入交互模式（流式输出: {'开启' if stream else '关闭'}），输入空行即可退出。")
    messages: List[Message] = [Message(role="system", content=system_prompt)]
    while True:
        try:
            user_input = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            break
        if not user_input:
            print("收到空输入，退出。")
            break
        messages.append(Message(role="user", content=user_input))
        print("--- AI 回复 ---")
        if stream and hasattr(client, "chat_stream"):
            tokens: List[str] = []
            for token in client.chat_stream(messages, max_tokens=max_tokens, temperature=temperature):
                tokens.append(token)
                print(token, end="", flush=True)
            print()
            reply_text = "".join(tokens).strip()
            response = LLMResponse(
                text=reply_text,
                usage={
                    "prompt_tokens": len(user_input) * 2,
                    "completion_tokens": len(reply_text) * 2,
                    "total_tokens": (len(user_input) + len(reply_text)) * 2,
                },
                model=getattr(client, "deployment", getattr(client, "model", "streaming")),
            )
        else:
            response = client.chat(messages, max_tokens=max_tokens, temperature=temperature)
            print(response.text)

        messages.append(Message(role="assistant", content=response.text))
        if store:
            store.log(
                user_input=user_input,
                assistant_response=response.text,
                model=response.model,
                mode="text",
                usage_tokens=(response.usage or {}).get("total_tokens", 0),
            )
        _log_usage(response, tracker)


def run_voice_turn(
    conversation: ConversationManager,
    microphone: SoundDeviceMicrophone,
    speaker: SoundDeviceSpeaker,
    *,
    record_seconds: float,
    use_vad: bool,
    vad_silence: float,
    vad_aggressiveness: int,
    stream: bool = True,
    tracker: Optional[BillingTrackerProtocol],
    save_reply_audio: Optional[str],
    store: Optional[ConversationStore] = None,
) -> None:
    print(f"\n{'='*60}")
    if use_vad:
        print(f"VAD 录音模式（最长 {record_seconds:.0f} 秒，静音 {vad_silence:.0f} 秒自动停止，流式流水线: {'开启' if stream else '关闭'}）")
    else:
        print(f"准备录制语音（{record_seconds:.1f} 秒，流式流水线: {'开启' if stream else '关闭'}）")
    print("请在提示后开始说话...")
    print(f"{'='*60}")

    try:
        if use_vad:
            audio_bytes = microphone.record_with_vad(
                max_duration=record_seconds,
                silence_duration=vad_silence,
                vad_aggressiveness=vad_aggressiveness,
                show_progress=True,
            )
        else:
            audio_bytes = microphone.record(record_seconds, show_progress=True)

            # 显示录音统计
            stats = microphone.get_last_recording_stats()
            if stats and stats['mean_amplitude'] < 100:
                print("\n⚠ 警告: 录音音量过低，可能影响识别效果")
                retry = input("是否重新录制？(y/n): ").strip().lower()
                if retry == 'y':
                    audio_bytes = microphone.record(record_seconds, show_progress=True)

        print("\n正在识别语音...")
        if stream:
            print(f"\n{'='*60}")
            print("AI 回复 (流式并发播放中...):")
            print(f"{'='*60}")
            result = conversation.handle_turn_stream(
                audio_bytes,
                speaker=speaker,
                on_token_callback=lambda token: print(token, end="", flush=True),
                play_audio=True,
            )
            print(f"\n{'='*60}")
        else:
            result = conversation.handle_turn(audio_bytes)
            print(f"✓ 识别结果: {result.transcript}")
            print(f"\n{'='*60}")
            print("AI 回复:")
            print(f"{'='*60}")
            print(result.response.text)
            print(f"{'='*60}")

        logger.info("[语音] 用户: %s", result.transcript)
        logger.info("[语音] AI: %s", result.response.text)
        if store:
            store.log(
                user_input=result.transcript,
                assistant_response=result.response.text,
                model=result.response.model,
                mode="voice",
                usage_tokens=(result.response.usage or {}).get("total_tokens", 0),
            )

        _log_usage(
            result.response,
            tracker,
            stt_duration=result.stt_duration_seconds,
            tts_characters=result.tts_characters,
        )

        if not stream and result.audio_reply:
            print("\n正在播放回复...")
            try:
                speaker.play(result.audio_reply)
                print("✓ 播放完成")
            except SoundDeviceUnavailable as exc:
                print(f"✗ 音频播放失败：{exc}")

        if save_reply_audio and result.audio_reply:
            output_path = Path(save_reply_audio)
            output_path.write_bytes(result.audio_reply)
            print(f"✓ 已保存语音到 {output_path}")

    except Exception as e:
        print(f"\n✗ 语音处理失败: {e}")
        raise


def _listen_for_wake_word(
    detector: WakeWordDetector,
    keywords: list[str],
    device: Optional[int],
) -> tuple[bool, str]:
    """单次监听唤醒词，检测到后立即退出并释放麦克风流"""
    import sounddevice as sd

    with sd.RawInputStream(
        samplerate=detector.sample_rate,
        channels=1,
        dtype='int16',
        blocksize=detector.frame_length,
        device=device,
    ) as mic_stream:
        while True:
            audio_frame, overflowed = mic_stream.read(detector.frame_length)
            if overflowed:
                continue
            detected, keyword_index = detector.process_audio(audio_frame.tobytes())
            if detected:
                kw = keywords[keyword_index] if keyword_index < len(keywords) else "唤醒词"
                return True, kw


def run_wake_word_loop(
    conversation: ConversationManager,
    microphone: SoundDeviceMicrophone,
    speaker: SoundDeviceSpeaker,
    *,
    wake_word_settings: Any,
    record_seconds: float,
    use_vad: bool,
    vad_silence: float,
    vad_aggressiveness: int,
    stream: bool = True,
    tracker: Optional[BillingTrackerProtocol],
    save_reply_audio: Optional[str],
    store: Optional[ConversationStore] = None,
) -> None:
    """唤醒词监听循环：持续监听唤醒词，检测到后开始对话，支持播放中随时喊唤醒词打断 (Barge-in)"""
    detector = create_wake_word_detector(wake_word_settings)
    if detector is None:
        print("❌ 唤醒词检测器初始化失败")
        return

    print(f"\n{'='*60}")
    print("🎙️  唤醒词监听模式（支持随时打断 Barge-in）")
    print(f"{'='*60}")
    print(f"唤醒词: {', '.join(wake_word_settings.keywords)}")
    print(f"采样率: {detector.sample_rate} Hz")
    print(f"帧长度: {detector.frame_length} 样本")
    print("\n请说出唤醒词开始对话（AI 回答期间亦可随时喊唤醒词打断）...")
    print("按 Ctrl+C 退出")
    print(f"{'='*60}\n")

    try:
        with detector:
            print("👂 正在监听唤醒词...\n")
            direct_listen_next = False  # 是否因打断直接进入录音状态

            while True:
                if not direct_listen_next:
                    detected, keyword = _listen_for_wake_word(
                        detector,
                        wake_word_settings.keywords,
                        microphone.device,
                    )
                    if not detected:
                        break
                    print(f"\n✨ 检测到唤醒词: {keyword}")
                    print(f"{'='*60}")
                else:
                    direct_listen_next = False

                # 开始录音和对话
                try:
                    if use_vad:
                        audio_bytes = microphone.record_with_vad(
                            max_duration=record_seconds,
                            silence_duration=vad_silence,
                            vad_aggressiveness=vad_aggressiveness,
                            show_progress=True,
                        )
                    else:
                        audio_bytes = microphone.record(record_seconds, show_progress=True)

                    print("\n正在识别语音...")
                    if stream:
                        print(f"\n{'='*60}")
                        print("AI 回复 (流式并发播放中，可随时喊唤醒词打断):")
                        print(f"{'='*60}")
                        result = conversation.handle_turn_stream(
                            audio_bytes,
                            speaker=speaker,
                            on_token_callback=lambda token: print(token, end="", flush=True),
                            play_audio=True,
                            barge_in_detector=detector,
                            barge_in_device=microphone.device,
                            on_barge_in_callback=lambda idx: print(f"\n\n⚡ [打断] 检测到唤醒词打断，已停止播放！", flush=True),
                        )
                        print(f"\n{'='*60}")
                    else:
                        result = conversation.handle_turn(audio_bytes)
                        print(f"✓ 识别结果: {result.transcript}")
                        print(f"\n{'='*60}")
                        print("AI 回复:")
                        print(f"{'='*60}")
                        print(result.response.text)
                        print(f"{'='*60}")

                    if store:
                        store.log(
                            user_input=result.transcript,
                            assistant_response=result.response.text,
                            model=result.response.model,
                            mode="wake_word",
                            usage_tokens=(result.response.usage or {}).get("total_tokens", 0),
                        )

                    _log_usage(
                        result.response,
                        tracker,
                        stt_duration=result.stt_duration_seconds,
                        tts_characters=result.tts_characters,
                    )

                    if not stream and result.audio_reply:
                        print("\n正在播放回复...")
                        try:
                            speaker.play(result.audio_reply)
                            print("✓ 播放完成")
                        except SoundDeviceUnavailable as exc:
                            print(f"✗ 音频播放失败：{exc}")

                    if save_reply_audio and result.audio_reply:
                        output_path = Path(save_reply_audio)
                        output_path.write_bytes(result.audio_reply)
                        print(f"✓ 已保存语音到 {output_path}")

                    if result.interrupted:
                        print("\n⚡ [无缝流转] 已被打断，正在为您倾听新问题...")
                        time.sleep(0.15)  # 150ms 消除扬声器混响残音
                        direct_listen_next = True
                    else:
                        print(f"\n{'='*60}")
                        print("👂 继续监听唤醒词...\n")
                        direct_listen_next = False

                except Exception as exc:
                    print(f"\n✗ 对话处理出错: {exc}")
                    print(f"{'='*60}")
                    print("👂 继续监听唤醒词...\n")
                    direct_listen_next = False

    except KeyboardInterrupt:
        print("\n\n👋 退出唤醒词监听模式")
    except Exception as exc:
        print(f"\n❌ 唤醒词监听出错: {exc}")

    except KeyboardInterrupt:
        print("\n\n👋 退出唤醒词监听模式")
    except Exception as exc:
        print(f"\n❌ 唤醒词监听出错: {exc}")


def main() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = build_arg_parser().parse_args()
    setup_logging(level=args.log_level, log_file=args.log_file)

    # 处理唤醒词列表请求
    if args.list_wake_words:
        print("\n支持的内置唤醒词:")
        print("=" * 40)
        for keyword in list_builtin_keywords():
            print(f"  • {keyword}")
        print("\n使用方法:")
        print("  在 .env 中设置: WAKE_WORD_KEYWORDS=jarvis,computer")
        print("  或使用 --wake-word 参数启动监听\n")
        return

    # 处理设备列表请求
    if args.list_devices:
        try:
            list_audio_devices()
        except SoundDeviceUnavailable as e:
            print(f"错误: {e}")
        return

    # 处理麦克风测试请求
    if args.test_microphone:
        try:
            success = test_microphone(
                duration=args.record_seconds,
                device=args.input_device,
            )
            if success:
                print("\n✓ 麦克风测试通过！可以开始使用语音功能。")
            else:
                print("\n✗ 麦克风测试未通过，请检查设备设置。")
        except SoundDeviceUnavailable as e:
            print(f"错误: {e}")
        return

    config = AppConfig.from_env()

    # 处理命令行对 Web Search 配置的覆盖
    if args.web_search is not None:
        config.web_search.enabled = args.web_search
    if args.search_provider:
        config.web_search.provider = args.search_provider

    # 处理命令行对 Provider 的覆盖
    if args.provider:
        config.responses_provider = args.provider

    target_provider = (config.responses_provider or "azure").strip().lower()

    # 初始化搜索引擎 (仅在传统 Chat Completions 模式下才需要本地 Tavily/DuckDuckGo/Bing 引擎)
    if target_provider in ("azure", "openai"):
        search_engine = None  # Responses API 使用模型原生内置 Web Search (web_search_preview)
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

    # 用配置初始化 LLM 客户端：统一通过 Responses API 或传统 Azure Chat 调度
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
    tracker: Optional[BillingTrackerProtocol] = None
    if config.billing.enabled:
        tracker = create_billing_tracker(config.billing)
        if tracker is None:
            logger.warning("计费插件 '%s' 未注册，跳过费用记录。", config.billing.provider)
    else:
        logger.info("计费追踪已禁用，可通过 ENABLE_BILLING 配置重新开启。")

    # 对话记录存储（与计费共用同一个 DB）
    store = ConversationStore(config.billing.storage_path)

    speech_service = create_speech_service(config.speech, retry_settings=config.retry)
    if args.voice_turn or args.wake_word:
        if speech_service is None:
            raise SystemExit(
                "未启用 Azure Speech，无法执行语音对话。\n"
                "请在 .env 中设置 AZURE_SPEECH_KEY 和 AZURE_SPEECH_REGION（或 STT/TTS endpoints）"
            )
        try:
            audio_settings = AudioSettings(sample_rate=config.speech.sample_rate)
            microphone = SoundDeviceMicrophone(audio_settings, device=args.input_device)
            speaker = SoundDeviceSpeaker(device=args.output_device)

            # 如果没有指定设备，显示当前使用的设备
            if args.input_device is None or args.output_device is None:
                print("\n提示: 使用 --list-devices 查看所有可用设备")
                print("      使用 --test-microphone 测试麦克风")
                print("      使用 --input-device <ID> 和 --output-device <ID> 指定设备\n")

        except SoundDeviceUnavailable as exc:
            raise SystemExit(f"麦克风/扬声器不可用: {exc}")

        # 初始化儿童安全过滤器（如果启用）
        safety_filter = None
        if config.child_safety.enabled:
            checkmark = '✓'
            crossmark = '✗'
            print("\n👶 儿童安全模式已启用")
            print(f"   过滤级别: {config.child_safety.filter_level}")
            print(f"   本地黑名单: {checkmark if config.child_safety.use_local_blacklist else crossmark}")
            print(f"   Azure 过滤: {checkmark if config.child_safety.enable_azure_content_filter else crossmark}")
            print(f"   对话日志: {checkmark if config.child_safety.log_all_conversations else crossmark}")
            print()
            safety_filter = ChildSafetyFilter(config.child_safety)
            # 如果启用儿童模式，使用儿童系统提示词
            if not args.system_prompt:
                args.system_prompt = config.child_safety.child_system_prompt

        conversation = ConversationManager(
            llm_client=client,
            speech_service=speech_service,
            system_prompt=args.system_prompt,
            safety_filter=safety_filter,
        )

        # 唤醒词监听模式
        if args.wake_word:
            if not config.wake_word.enabled:
                print("⚠️  唤醒词功能未启用")
                print("   请在 .env 中设置:")
                print("     ENABLE_WAKE_WORD=true")
                print("     PORCUPINE_ACCESS_KEY=your_access_key")
                print("     WAKE_WORD_KEYWORDS=jarvis,computer")
                print("\n   从 https://console.picovoice.ai/ 获取免费 Access Key")
                return

            run_wake_word_loop(
                conversation,
                microphone,
                speaker,
                wake_word_settings=config.wake_word,
                record_seconds=args.record_seconds,
                use_vad=args.use_vad,
                vad_silence=args.vad_silence,
                vad_aggressiveness=args.vad_aggressiveness,
                stream=args.stream,
                tracker=tracker,
                save_reply_audio=args.save_reply_audio,
                store=store,
            )
            return

        # 单次语音对话
        run_voice_turn(
            conversation,
            microphone,
            speaker,
            record_seconds=args.record_seconds,
            use_vad=args.use_vad,
            vad_silence=args.vad_silence,
            vad_aggressiveness=args.vad_aggressiveness,
            stream=args.stream,
            tracker=tracker,
            save_reply_audio=args.save_reply_audio,
            store=store,
        )
        return

    if args.prompt:
        # 单轮提示
        run_single_turn(
            client,
            args.prompt,
            system_prompt=args.system_prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            stream=args.stream,
            tracker=tracker,
            store=store,
        )
    else:
        # REPL 模式
        interactive_loop(
            client,
            system_prompt=args.system_prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            stream=args.stream,
            tracker=tracker,
            store=store,
        )


if __name__ == "__main__":
    main()
