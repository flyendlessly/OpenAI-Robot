"""Interactive commands: single turn, interactive REPL, and single voice turn."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ...audio_io import SoundDeviceUnavailable
from ...context import AppContext
from ...llm_client import LLMResponse, Message
from ...logger import get_logger

logger = get_logger("cli.interactive")


def run_single_turn_command(ctx: AppContext, prompt: str) -> int:
    """执行单轮文本提示并输出 AI 回复"""
    system_prompt = ctx.args.system_prompt
    max_tokens = ctx.args.max_tokens
    temperature = ctx.args.temperature
    stream = ctx.args.stream

    messages: List[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=prompt),
    ]
    print("--- AI 回复 ---")
    if stream and hasattr(ctx.llm_client, "chat_stream"):
        tokens: List[str] = []
        for token in ctx.llm_client.chat_stream(
            messages, max_tokens=max_tokens, temperature=temperature
        ):
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
            model=getattr(
                ctx.llm_client, "deployment", getattr(ctx.llm_client, "model", "streaming")
            ),
        )
    else:
        response = ctx.llm_client.chat(messages, max_tokens=max_tokens, temperature=temperature)
        print(response.text)

    ctx.log_turn(
        user_input=prompt,
        assistant_response=response.text,
        model=response.model,
        mode="text",
        usage_tokens=(response.usage or {}).get("total_tokens", 0),
    )
    ctx.log_usage(response)
    return 0


def run_interactive_loop_command(ctx: AppContext) -> int:
    """进入终端多轮交互 REPL 模式"""
    system_prompt = ctx.args.system_prompt
    max_tokens = ctx.args.max_tokens
    temperature = ctx.args.temperature
    stream = ctx.args.stream

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
        if stream and hasattr(ctx.llm_client, "chat_stream"):
            tokens: List[str] = []
            for token in ctx.llm_client.chat_stream(
                messages, max_tokens=max_tokens, temperature=temperature
            ):
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
                model=getattr(
                    ctx.llm_client, "deployment", getattr(ctx.llm_client, "model", "streaming")
                ),
            )
        else:
            response = ctx.llm_client.chat(messages, max_tokens=max_tokens, temperature=temperature)
            print(response.text)

        messages.append(Message(role="assistant", content=response.text))
        ctx.log_turn(
            user_input=user_input,
            assistant_response=response.text,
            model=response.model,
            mode="text",
            usage_tokens=(response.usage or {}).get("total_tokens", 0),
        )
        ctx.log_usage(response)

    return 0


def run_voice_turn_command(ctx: AppContext) -> int:
    """录制一次语音并调用语音助手完成对话"""
    if ctx.conversation_manager is None or ctx.microphone is None or ctx.speaker is None:
        raise RuntimeError("语音组件未成功就绪，无法执行语音轮次")

    conversation = ctx.conversation_manager
    microphone = ctx.microphone
    speaker = ctx.speaker

    record_seconds = ctx.args.record_seconds
    use_vad = ctx.args.use_vad
    vad_silence = ctx.args.vad_silence
    vad_aggressiveness = ctx.args.vad_aggressiveness
    stream = ctx.args.stream
    save_reply_audio = ctx.args.save_reply_audio

    print(f"\n{'='*60}")
    if use_vad:
        print(
            f"VAD 录音模式（最长 {record_seconds:.0f} 秒，静音 {vad_silence:.0f} 秒自动停止，流式流水线: {'开启' if stream else '关闭'}）"
        )
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
            stats = microphone.get_last_recording_stats()
            if stats and stats["mean_amplitude"] < 100:
                print("\n⚠ 警告: 录音音量过低，可能影响识别效果")
                retry = input("是否重新录制？(y/n): ").strip().lower()
                if retry == "y":
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

        ctx.log_turn(
            user_input=result.transcript,
            assistant_response=result.response.text,
            model=result.response.model,
            mode="voice",
            usage_tokens=(result.response.usage or {}).get("total_tokens", 0),
        )

        ctx.log_usage(
            result.response,
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

        return 0

    except Exception as e:
        print(f"\n✗ 语音处理失败: {e}")
        raise
