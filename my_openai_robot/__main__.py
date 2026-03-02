"""Entry point for CLI testing."""
# 文本 & 语音 CLI：便于验证 Azure LLM / Speech / 音频链路
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .audio_io import (
    AudioSettings,
    SoundDeviceMicrophone,
    SoundDeviceSpeaker,
    SoundDeviceUnavailable,
    list_audio_devices,
    test_microphone,
)
from .billing_tracker import BillingTrackerProtocol, create_billing_tracker
from .config import AppConfig
from .conversation_manager import ConversationManager
from .llm_client import AzureLLMClient, LLMResponse, Message
from .speech_service import create_speech_service


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
    parser.add_argument("--list-devices", action="store_true", help="列出所有可用音频设备")
    parser.add_argument("--test-microphone", action="store_true", help="测试麦克风是否正常工作")
    parser.add_argument("--input-device", type=int, help="指定输入设备 ID（使用 --list-devices 查看）")
    parser.add_argument("--output-device", type=int, help="指定输出设备 ID（使用 --list-devices 查看）")
    return parser


def _log_usage(response: LLMResponse, tracker: Optional[BillingTrackerProtocol]) -> None:
    if not response.usage:
        return
    print("--- 用量 ---")
    print(json.dumps(response.usage, ensure_ascii=False, indent=2))
    if tracker:
        usage_record = tracker.record_usage(response.usage)
        monthly_cost = tracker.get_monthly_cost()
        print(f"本次预估费用: ${usage_record.cost_usd:.6f}")
        print(f"本月累计费用: ${monthly_cost:.4f} / ${tracker.settings.monthly_budget_usd:.2f}")
        if tracker.should_warn(monthly_cost):
            print("⚠ 达到预算告警阈值，请关注使用量！")


def run_single_turn(
    client: AzureLLMClient,
    prompt: str,
    *,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    tracker: Optional[BillingTrackerProtocol] = None,
) -> None:
    # 组装最小对话上下文并调用 Azure
    messages: List[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=prompt),
    ]
    response = client.chat(messages, max_tokens=max_tokens, temperature=temperature)
    print("--- AI 回复 ---")
    print(response.text)
    _log_usage(response, tracker)


def interactive_loop(
    client: AzureLLMClient,
    *,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    tracker: Optional[BillingTrackerProtocol] = None,
) -> None:
    # 简单 REPL，便于连续对话测试
    print("进入交互模式，输入空行即可退出。")
    while True:
        try:
            user_input = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            break
        if not user_input:
            print("收到空输入，退出。")
            break
        run_single_turn(
            client,
            user_input,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            tracker=tracker,
        )


def run_voice_turn(
    conversation: ConversationManager,
    microphone: SoundDeviceMicrophone,
    speaker: SoundDeviceSpeaker,
    *,
    record_seconds: float,
    use_vad: bool,
    vad_silence: float,
    vad_aggressiveness: int,
    tracker: Optional[BillingTrackerProtocol],
    save_reply_audio: Optional[str],
) -> None:
    print(f"\n{'='*60}")
    if use_vad:
        print(f"VAD 录音模式（最长 {record_seconds:.0f} 秒，静音 {vad_silence:.0f} 秒自动停止）")
    else:
        print(f"准备录制语音（{record_seconds:.1f} 秒）")
    print(f"请在提示后开始说话...")
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
        result = conversation.handle_turn(audio_bytes)
        
        print(f"\n✓ 识别结果: {result.transcript}")
        print(f"\n{'='*60}")
        print("AI 回复:")
        print(f"{'='*60}")
        print(result.response.text)
        print(f"{'='*60}")
        
        _log_usage(result.response, tracker)
        
        if result.audio_reply:
            print("\n正在播放回复...")
            try:
                speaker.play(result.audio_reply)
                print("✓ 播放完成")
            except SoundDeviceUnavailable as exc:
                print(f"✗ 音频播放失败：{exc}")
            
            if save_reply_audio:
                output_path = Path(save_reply_audio)
                output_path.write_bytes(result.audio_reply)
                print(f"✓ 已保存语音到 {output_path}")
    
    except Exception as e:
        print(f"\n✗ 语音处理失败: {e}")
        raise


def main() -> None:
    args = build_arg_parser().parse_args()
    
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
                device=args.input_device
            )
            if success:
                print("\n✓ 麦克风测试通过！可以开始使用语音功能。")
            else:
                print("\n✗ 麦克风测试未通过，请检查设备设置。")
        except SoundDeviceUnavailable as e:
            print(f"错误: {e}")
        return
    
    config = AppConfig.from_env()
    # 用配置初始化 LLM 客户端
    client = AzureLLMClient(
        endpoint=config.azure.endpoint,
        api_key=config.azure.api_key,
        deployment=config.azure.deployment,
        api_version=config.azure.api_version,
    )
    tracker: Optional[BillingTrackerProtocol] = None
    if config.billing.enabled:
        tracker = create_billing_tracker(config.billing)
        if tracker is None:
            print(
                f"计费插件 '{config.billing.provider}' 未注册，跳过费用记录。"
            )
    else:
        print("计费追踪已禁用，可通过 ENABLE_BILLING 配置重新开启。")
    
    speech_service = create_speech_service(config.speech)
    if args.voice_turn:
        if speech_service is None:
            raise SystemExit(
                "未启用 Azure Speech，无法执行语音对话。\\n"
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
                print("      使用 --input-device <ID> 和 --output-device <ID> 指定设备\\n")
        
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
        run_voice_turn(
            conversation,
            microphone,
            speaker,
            record_seconds=args.record_seconds,
            use_vad=args.use_vad,
            vad_silence=args.vad_silence,
            vad_aggressiveness=args.vad_aggressiveness,
            tracker=tracker,
            save_reply_audio=args.save_reply_audio,
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
            tracker=tracker,
        )
    else:
        # REPL 模式
        interactive_loop(
            client,
            system_prompt=args.system_prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            tracker=tracker,
        )


if __name__ == "__main__":
    main()
