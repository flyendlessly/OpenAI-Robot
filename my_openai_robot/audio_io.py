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
