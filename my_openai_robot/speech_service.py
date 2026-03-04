"""Speech to text and text to speech abstraction layer."""
# 语音服务抽象 + Azure Speech 默认实现
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:  # pragma: no cover - 仅在依赖缺失时触发
    speechsdk = None

if TYPE_CHECKING:  # 避免运行时循环导入
    from .config import SpeechSettings


@dataclass
class SpeechResult:
    """语音识别结果（文本 + 置信度 + 时长）"""

    text: str
    confidence: float | None = None
    duration_seconds: float = 0.0  # 音频时长（用于计费）


class SpeechService:
    """STT/TTS 统一接口，子类实现具体服务"""

    def transcribe(self, audio_bytes: bytes) -> SpeechResult:
        """语音转文本"""
        raise NotImplementedError

    def synthesize(self, text: str) -> bytes:
        """文本转语音"""
        raise NotImplementedError


class AzureSpeechService(SpeechService):
    """封装 Azure Cognitive Services Speech SDK"""

    def __init__(self, settings: "SpeechSettings") -> None:
        if speechsdk is None:
            raise RuntimeError("未安装 azure-cognitiveservices-speech，无法启用语音功能")
        if not settings.speech_key:
            raise ValueError("Azure Speech key 未配置")
        if not (settings.speech_region or settings.stt_endpoint or settings.tts_endpoint):
            raise ValueError("必须提供 speech_region 或独立的 STT/TTS endpoint")
        self.settings = settings
        self.stt_config = self._build_config(settings.stt_endpoint)
        self.tts_config = self._build_config(settings.tts_endpoint)
        self.stt_config.speech_recognition_language = settings.stt_language
        self.tts_config.speech_synthesis_voice_name = settings.voice_name
        self.sample_rate = settings.sample_rate

    def _build_config(self, endpoint: Optional[str]) -> "speechsdk.SpeechConfig":
        if endpoint:
            config = speechsdk.SpeechConfig(endpoint=endpoint, subscription=self.settings.speech_key)
        else:
            config = speechsdk.SpeechConfig(
                subscription=self.settings.speech_key,
                region=self.settings.speech_region,
            )
        return config

    def transcribe(self, audio_bytes: bytes) -> SpeechResult:
        if not audio_bytes:
            return SpeechResult(text="", confidence=None)
        tmp_path = None
        try:
            # 使用 delete=False 避免被 Azure SDK 锁定时删除失败
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            audio_config = speechsdk.audio.AudioConfig(filename=tmp_path)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.stt_config,
                audio_config=audio_config,
            )
            result = recognizer.recognize_once_async().get()
            
            # 关闭 recognizer 以释放文件句柄
            del recognizer
            del audio_config
            
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                return SpeechResult(text=result.text, confidence=None)
            if result.reason == speechsdk.ResultReason.NoMatch:
                return SpeechResult(text="", confidence=None)
            cancellation = result.cancellation_details if hasattr(result, "cancellation_details") else None
            raise RuntimeError(f"语音识别失败: {cancellation}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except PermissionError:
                    # Windows 下可能需要延迟删除
                    import time
                    time.sleep(0.1)
                    try:
                        os.unlink(tmp_path)
                    except:
                        pass  # 忽略删除失败，临时文件会被系统清理

    def synthesize(self, text: str) -> bytes:
        if not text:
            return b""
        
        # audio_config=None 表示仅返回音频数据，不播放
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.tts_config,
            audio_config=None,
        )
        result = synthesizer.speak_text_async(text).get()
        
        # 清理资源
        del synthesizer
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return bytes(result.audio_data)
        cancellation = result.cancellation_details if hasattr(result, "cancellation_details") else None
        raise RuntimeError(f"语音合成失败: {cancellation}")


def create_speech_service(settings: "SpeechSettings") -> Optional[SpeechService]:
    """根据配置创建语音服务，未启用或缺少依赖时返回 None"""
    if not settings.use_azure_speech:
        return None
    if not settings.speech_key or not settings.speech_region:
        return None
    try:
        return AzureSpeechService(settings)
    except Exception as exc:  # pragma: no cover - 主要用于运行时提示
        print(f"初始化语音服务失败: {exc}")
        return None
