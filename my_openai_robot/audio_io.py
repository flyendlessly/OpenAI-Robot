"""Audio input/output utilities for Raspberry Pi."""
# 音频输入/输出抽象层：封装基于 sounddevice 的采集与播放，返回标准 PCM/WAV 数据
from __future__ import annotations

import io
import sys
import threading
import time
import wave
from dataclasses import dataclass
from typing import Iterable, Protocol, Optional

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - 仅在依赖缺失时触发
    sd = None

try:
    import webrtcvad
except ImportError:  # pragma: no cover - VAD 为可选依赖
    webrtcvad = None


class AudioStream(Protocol):
    """泛化音频输入流，便于替换具体实现"""

    def __iter__(self) -> Iterable[bytes]:
        ...

    def close(self) -> None:
        ...


@dataclass
class AudioSettings:
    """音频采样参数，Raspberry Pi 常用 16k 单声道"""

    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024


class SoundDeviceUnavailable(RuntimeError):
    """提示用户安装 sounddevice 依赖"""


def _require_sounddevice() -> None:
    if sd is None:
        raise SoundDeviceUnavailable(
            "未检测到 sounddevice，请运行 'pip install sounddevice' 并确保系统音频驱动可用"
        )


def _frames_to_wav_bytes(frames: np.ndarray, settings: AudioSettings) -> bytes:
    frames = np.asarray(frames, dtype=np.int16)
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(settings.channels)
            wav.setsampwidth(2)  # int16
            wav.setframerate(settings.sample_rate)
            wav.writeframes(frames.tobytes())
        return buffer.getvalue()


def _wav_bytes_to_frames(audio_data: bytes) -> tuple[np.ndarray, int, int]:
    with wave.open(io.BytesIO(audio_data)) as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        frames = wav.readframes(wav.getnframes())
    array = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        array = array.reshape(-1, channels)
    return array, sample_rate, channels


class SoundDeviceMicrophone(AudioStream):
    """基于 sounddevice 的麦克风实现，返回 WAV bytes"""

    def __init__(self, settings: AudioSettings | None = None, device: Optional[int] = None) -> None:
        self.settings = settings or AudioSettings()
        self.device = device
        self._recording = False
        self._frames = None

    def record(self, duration_seconds: float, show_progress: bool = True) -> bytes:
        """录制音频，支持进度显示和音量指示"""
        _require_sounddevice()
        self._recording = True
        self._frames = None
        
        total_frames = int(duration_seconds * self.settings.sample_rate)
        frames_list = []
        
        def callback(indata, frames, time_info, status):
            if status:
                print(f"\n录音状态: {status}", file=sys.stderr)
            frames_list.append(indata.copy())
        
        if show_progress:
            print(f"\n开始录音 {duration_seconds:.1f} 秒...")
            # 启动音量指示器线程
            stop_indicator = threading.Event()
            indicator_thread = threading.Thread(
                target=self._show_volume_indicator,
                args=(frames_list, duration_seconds, stop_indicator)
            )
            indicator_thread.daemon = True
            indicator_thread.start()
        
        try:
            with sd.InputStream(
                samplerate=self.settings.sample_rate,
                channels=self.settings.channels,
                dtype="int16",
                device=self.device,
                callback=callback,
            ):
                sd.sleep(int(duration_seconds * 1000))
        finally:
            if show_progress:
                stop_indicator.set()
                indicator_thread.join(timeout=1)
                print("\n录音完成！")
            self._recording = False
        
        if not frames_list:
            raise RuntimeError("录音失败：未采集到音频数据")
        
        self._frames = np.concatenate(frames_list, axis=0)
        return _frames_to_wav_bytes(self._frames, self.settings)
    
    def _show_volume_indicator(self, frames_list, duration, stop_event):
        """实时显示音量指示器"""
        start_time = time.time()
        bar_width = 30
        
        while not stop_event.is_set():
            elapsed = time.time() - start_time
            if elapsed >= duration:
                break
            
            # 计算进度
            progress = min(elapsed / duration, 1.0)
            filled = int(bar_width * progress)
            bar = '█' * filled + '░' * (bar_width - filled)
            
            # 计算音量
            volume_bar = ''
            if frames_list:
                try:
                    recent_frames = frames_list[-1] if frames_list else np.array([[0]])
                    volume = np.abs(recent_frames).mean()
                    volume_normalized = min(volume / 3000.0, 1.0)  # 归一化到 0-1
                    volume_blocks = int(volume_normalized * 10)
                    volume_bar = '▮' * volume_blocks + '▯' * (10 - volume_blocks)
                except:
                    volume_bar = '▯' * 10
            else:
                volume_bar = '▯' * 10
            
            # 输出进度条
            sys.stdout.write(f'\r进度: [{bar}] {progress*100:.0f}% | 音量: [{volume_bar}]')
            sys.stdout.flush()
            time.sleep(0.1)
    
    def get_last_recording_stats(self) -> Optional[dict]:
        """获取上次录音的统计信息"""
        if self._frames is None:
            return None
        return {
            "duration_seconds": len(self._frames) / self.settings.sample_rate,
            "max_amplitude": float(np.abs(self._frames).max()),
            "mean_amplitude": float(np.abs(self._frames).mean()),
            "frames": len(self._frames),
        }
    
    def record_with_vad(
        self,
        max_duration: float = 20.0,
        silence_duration: float = 2.0,
        vad_aggressiveness: int = 2,
        show_progress: bool = True,
    ) -> bytes:
        """使用 VAD 录音：检测到说话开始录音，静音指定时长后自动停止
        
        Args:
            max_duration: 最大录音时长（秒）
            silence_duration: 连续静音多久后停止（秒）
            vad_aggressiveness: WebRTC VAD 灵敏度 0-3，越高越不容易误触发
            show_progress: 是否显示进度和状态
        
        Returns:
            WAV 格式音频数据
        """
        _require_sounddevice()
        
        if webrtcvad is None:
            raise RuntimeError(
                "未安装 webrtcvad，无法使用 VAD 录音。\\n"
                "请运行: pip install webrtcvad"
            )
        
        # WebRTC VAD 只支持特定采样率
        if self.settings.sample_rate not in [8000, 16000, 32000, 48000]:
            raise ValueError(
                f"VAD 录音要求采样率为 8000/16000/32000/48000 Hz，"
                f"当前为 {self.settings.sample_rate} Hz"
            )
        
        # 初始化 VAD
        vad = webrtcvad.Vad(vad_aggressiveness)
        
        # WebRTC VAD 要求帧长度为 10/20/30 ms
        frame_duration_ms = 30  # 毫秒
        frame_size = int(self.settings.sample_rate * frame_duration_ms / 1000)
        
        # 状态管理
        is_speaking = False
        silence_frames = 0
        max_silence_frames = int(silence_duration / (frame_duration_ms / 1000))
        max_frames = int(max_duration / (frame_duration_ms / 1000))
        
        recorded_frames = []
        buffer_frames = []  # 预留缓冲，避免丢失开头
        buffer_size = int(0.3 / (frame_duration_ms / 1000))  # 300ms 缓冲
        
        frame_count = 0
        
        if show_progress:
            print(f"\\n等待说话...（最长 {max_duration:.0f} 秒，静音 {silence_duration:.0f} 秒自动停止）")
        
        def callback(indata, frames, time_info, status):
            nonlocal is_speaking, silence_frames, frame_count, recorded_frames, buffer_frames
            
            if status:
                print(f"\\n录音状态: {status}", file=sys.stderr)
            
            # 转换为 int16
            audio_frame = (indata * 32767).astype(np.int16).tobytes()
            
            # VAD 检测
            try:
                has_speech = vad.is_speech(audio_frame, self.settings.sample_rate)
            except Exception:
                has_speech = False
            
            if has_speech:
                # 检测到说话
                if not is_speaking:
                    # 刚开始说话，加入缓冲帧
                    is_speaking = True
                    recorded_frames.extend(buffer_frames)
                    if show_progress:
                        print("\\n✓ 检测到说话，开始录音...")
                
                recorded_frames.append(indata.copy())
                silence_frames = 0
            else:
                # 静音
                if is_speaking:
                    # 正在录音中遇到静音
                    recorded_frames.append(indata.copy())
                    silence_frames += 1
                else:
                    # 还没开始说话，保持缓冲
                    buffer_frames.append(indata.copy())
                    if len(buffer_frames) > buffer_size:
                        buffer_frames.pop(0)
            
            frame_count += 1
        
        # 开始录音
        try:
            with sd.InputStream(
                samplerate=self.settings.sample_rate,
                channels=self.settings.channels,
                dtype="float32",
                blocksize=frame_size,
                device=self.device,
                callback=callback,
            ):
                start_time = time.time()
                
                while frame_count < max_frames:
                    if is_speaking and silence_frames >= max_silence_frames:
                        if show_progress:
                            print(f"\\n✓ 检测到{silence_duration:.0f}秒静音，录音结束")
                        break
                    
                    elapsed = time.time() - start_time
                    if show_progress and frame_count % 10 == 0:  # 每 300ms 更新一次
                        status_icon = "🎤" if is_speaking else "⏸"
                        silence_sec = silence_frames * frame_duration_ms / 1000
                        sys.stdout.write(
                            f"\\r{status_icon} 时长: {elapsed:.1f}s / {max_duration:.0f}s "
                            f"| 静音: {silence_sec:.1f}s / {silence_duration:.0f}s"
                        )
                        sys.stdout.flush()
                    
                    time.sleep(0.1)
                
                if frame_count >= max_frames:
                    if show_progress:
                        print(f"\\n⏱ 达到最大时长 {max_duration:.0f} 秒，录音结束")
        
        finally:
            if show_progress:
                print()
        
        if not recorded_frames:
            if show_progress:
                print("⚠ 未检测到说话，录音为空")
            # 返回空白音频
            silence = np.zeros((int(self.settings.sample_rate * 0.5), self.settings.channels), dtype=np.float32)
            return _frames_to_wav_bytes((silence * 32767).astype(np.int16), self.settings)
        
        # 合并所有帧
        self._frames = (np.concatenate(recorded_frames, axis=0) * 32767).astype(np.int16)
        
        if show_progress:
            duration = len(self._frames) / self.settings.sample_rate
            print(f"✓ 录音完成！时长: {duration:.2f} 秒")
        
        return _frames_to_wav_bytes(self._frames, self.settings)

    def __iter__(self) -> Iterable[bytes]:  # pragma: no cover - streaming 暂未启用
        raise NotImplementedError("Streaming capture not implemented; use record() 采集定长音频")

    def close(self) -> None:  # pragma: no cover - 无需特殊清理
        return None


class SoundDeviceSpeaker:
    """基于 sounddevice 的扬声器播放"""

    def __init__(self, device: Optional[int] = None) -> None:
        self._available = sd is not None
        self.device = device

    def play(self, audio_data: bytes) -> None:
        if not audio_data:
            return
        _require_sounddevice()
        frames, sample_rate, _ = _wav_bytes_to_frames(audio_data)
        sd.play(frames, samplerate=sample_rate, device=self.device)
        sd.wait()


def list_audio_devices() -> None:
    """列出所有可用的音频设备"""
    _require_sounddevice()
    print("\n=== 可用音频设备 ===")
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        device_type = []
        if device['max_input_channels'] > 0:
            device_type.append("输入")
        if device['max_output_channels'] > 0:
            device_type.append("输出")
        type_str = "/".join(device_type) if device_type else "无"
        print(f"[{i}] {device['name']}")
        print(f"    类型: {type_str}")
        print(f"    采样率: {device['default_samplerate']} Hz")
        if device['max_input_channels'] > 0:
            print(f"    输入通道: {device['max_input_channels']}")
        if device['max_output_channels'] > 0:
            print(f"    输出通道: {device['max_output_channels']}")
        print()
    
    try:
        default_input = sd.query_devices(kind='input')
        print(f"默认输入设备: {default_input['name']}")
    except:
        print("默认输入设备: 未设置")
    
    try:
        default_output = sd.query_devices(kind='output')
        print(f"默认输出设备: {default_output['name']}")
    except:
        print("默认输出设备: 未设置")


def test_microphone(duration: float = 2.0, device: Optional[int] = None) -> bool:
    """测试麦克风是否正常工作"""
    try:
        _require_sounddevice()
        print(f"\n测试麦克风（录制 {duration} 秒）...")
        settings = AudioSettings()
        mic = SoundDeviceMicrophone(settings, device=device)
        audio_data = mic.record(duration, show_progress=True)
        
        stats = mic.get_last_recording_stats()
        if stats:
            print(f"\n录音统计:")
            print(f"  时长: {stats['duration_seconds']:.2f} 秒")
            print(f"  最大音量: {stats['max_amplitude']:.0f}")
            print(f"  平均音量: {stats['mean_amplitude']:.0f}")
            
            if stats['mean_amplitude'] < 100:
                print("  ⚠ 警告: 音量过低，请检查麦克风是否正常工作或靠近麦克风说话")
                return False
            elif stats['mean_amplitude'] > 20000:
                print("  ⚠ 警告: 音量过高，可能导致失真")
            else:
                print("  ✓ 麦克风工作正常")
        
        return True
    except Exception as e:
        print(f"✗ 麦克风测试失败: {e}")
        return False
