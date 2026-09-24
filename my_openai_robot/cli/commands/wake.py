"""Wake word continuous listening and barge-in execution command."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, List, Optional

from ...audio_io import SoundDeviceUnavailable
from ...context import AppContext
from ...logger import get_logger
from ...wake_word import WakeWordDetector, create_wake_word_detector

logger = get_logger("cli.wake")


def _listen_for_wake_word(
    detector: WakeWordDetector,
    keywords: list[str],
    device: Optional[int],
) -> tuple[bool, str]:
    """单次监听唤醒词，检测到后立即退出并释放麦克风流"""
    import numpy as np
    import sounddevice as sd

    if hasattr(detector, "reset"):
        detector.reset()

    start_time = time.time()
    low_volume_warned = False
    max_amp_seen = 0

    with sd.RawInputStream(
        samplerate=detector.sample_rate,
        channels=1,
        dtype="int16",
        blocksize=detector.frame_length,
        device=device,
    ) as mic_stream:
        while True:
            audio_frame, overflowed = mic_stream.read(detector.frame_length)
            if overflowed:
                continue
            frame_bytes = bytes(audio_frame)
            detected, keyword_index = detector.process_audio(frame_bytes)
            if detected:
                kw = keywords[keyword_index] if keyword_index < len(keywords) else "唤醒词"
                return True, kw

            # 诊断辅助：如果麦克风持续静音超过 5 秒，且最大振幅始终小于 60，提示用户检查麦克风
            if not low_volume_warned:
                samples = np.frombuffer(frame_bytes, dtype=np.int16)
                cur_amp = int(np.max(np.abs(samples)))
                if cur_amp > max_amp_seen:
                    max_amp_seen = cur_amp
                if time.time() - start_time > 5.0:
                    if max_amp_seen < 60:
                        print(
                            f"⚠️ [麦克风提示] 当前输入音量极微弱 (最大振幅 {max_amp_seen}/32767)。"
                            "若呼叫无反应，请靠近麦克风或在系统设置中调高麦克风音量。",
                            flush=True,
                        )
                        low_volume_warned = True


def run_wake_word_command(ctx: AppContext) -> int:
    """唤醒词监听循环：持续监听唤醒词，检测到后开始对话，支持播放中随时喊唤醒词打断 (Barge-in)"""
    if ctx.conversation_manager is None or ctx.microphone is None or ctx.speaker is None:
        raise RuntimeError("语音组件未就绪，无法启动唤醒词监听模式")

    if not ctx.config.wake_word.enabled:
        print("⚠️  唤醒词功能未启用")
        print("   请在 .env 中设置:")
        print("     ENABLE_WAKE_WORD=true")
        print("     WAKE_WORD_KEYWORDS=芝麻开门,你好小智,小智小智")
        return 1

    detector = create_wake_word_detector(ctx.config.wake_word)
    if detector is None:
        print("❌ 唤醒词检测器初始化失败")
        return 1

    conversation = ctx.conversation_manager
    microphone = ctx.microphone
    speaker = ctx.speaker
    wake_settings = ctx.config.wake_word

    record_seconds = ctx.args.record_seconds
    use_vad = ctx.args.use_vad
    vad_silence = ctx.args.vad_silence
    vad_aggressiveness = ctx.args.vad_aggressiveness
    stream = ctx.args.stream
    save_reply_audio = ctx.args.save_reply_audio

    print(f"\n{'='*60}")
    print("🎙️  唤醒词监听模式（支持随时打断 Barge-in）")
    print(f"{'='*60}")
    print(f"唤醒词: {', '.join(wake_settings.keywords)}")
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
                        wake_settings.keywords,
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
                            on_barge_in_callback=lambda idx: print(
                                "\n\n⚡ [打断] 检测到唤醒词打断，已停止播放！", flush=True
                            ),
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

                    ctx.log_turn(
                        user_input=result.transcript,
                        assistant_response=result.response.text,
                        model=result.response.model,
                        mode="wake_word",
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

        return 0

    except KeyboardInterrupt:
        print("\n\n👋 退出唤醒词监听模式")
        return 0
    except Exception as exc:
        print(f"\n❌ 唤醒词监听出错: {exc}")
        return 1
