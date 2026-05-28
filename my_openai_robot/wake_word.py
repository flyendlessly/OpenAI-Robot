"""Wake word detection using Picovoice Porcupine"""
# 唤醒词检测模块：基于 Porcupine 实现本地唤醒词识别
from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional, Protocol

try:
    import pvporcupine
except ImportError:
    pvporcupine = None

from .config import WakeWordSettings


class WakeWordDetector(Protocol):
    """唤醒词检测器接口"""
    
    def process_audio(self, audio_frame: bytes) -> tuple[bool, int]:
        """
        处理音频帧
        
        Args:
            audio_frame: PCM 音频数据
            
        Returns:
            (是否检测到唤醒词, 唤醒词索引)
        """
        ...
    
    def close(self) -> None:
        """释放资源"""
        ...


class PorcupineWakeWordDetector:
    """基于 Picovoice Porcupine 的唤醒词检测器"""
    
    def __init__(self, settings: WakeWordSettings):
        if pvporcupine is None:
            raise ImportError(
                "pvporcupine 未安装。请运行: pip install pvporcupine"
            )
        
        if not settings.enabled:
            raise ValueError("唤醒词检测未启用")
        
        if not settings.access_key:
            raise ValueError(
                "需要 Picovoice Access Key。请从 https://console.picovoice.ai/ 获取"
            )
        
        self.settings = settings
        
        # 构建参数
        kwargs = {
            "access_key": settings.access_key,
        }
        
        # 使用内置关键词或自定义关键词文件
        if settings.keyword_paths:
            kwargs["keyword_paths"] = [str(p) for p in settings.keyword_paths]
        else:
            kwargs["keywords"] = settings.keywords
        
        # 设置灵敏度
        if settings.sensitivities:
            kwargs["sensitivities"] = settings.sensitivities
        
        # 加载自定义模型（如果提供）
        if settings.model_path:
            kwargs["model_path"] = str(settings.model_path)
        
        try:
            self.porcupine = pvporcupine.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"初始化 Porcupine 失败: {e}")
        
        self.frame_length = self.porcupine.frame_length
        self.sample_rate = self.porcupine.sample_rate
    
    def process_audio(self, audio_frame: bytes) -> tuple[bool, int]:
        """
        处理音频帧
        
        Args:
            audio_frame: PCM 音频数据（16-bit, 单声道）
            
        Returns:
            (是否检测到唤醒词, 唤醒词索引，-1 表示未检测到)
        """
        # 将字节转换为 16-bit PCM 样本
        pcm = struct.unpack_from("h" * self.frame_length, audio_frame)
        
        # 检测唤醒词
        keyword_index = self.porcupine.process(pcm)
        
        if keyword_index >= 0:
            return True, keyword_index
        return False, -1
    
    def close(self) -> None:
        """释放 Porcupine 资源"""
        if hasattr(self, 'porcupine'):
            self.porcupine.delete()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_wake_word_detector(settings: WakeWordSettings) -> Optional[PorcupineWakeWordDetector]:
    """
    创建唤醒词检测器
    
    Args:
        settings: 唤醒词配置
        
    Returns:
        PorcupineWakeWordDetector 实例，如果未启用则返回 None
    """
    if not settings.enabled:
        return None
    
    try:
        return PorcupineWakeWordDetector(settings)
    except Exception as e:
        print(f"⚠️  唤醒词检测器初始化失败: {e}")
        return None


def list_builtin_keywords() -> list[str]:
    """列出 Porcupine 支持的内置唤醒词"""
    # 返回已知的内置唤醒词列表（Porcupine 2.x/3.x 支持的标准词）
    return [
        "alexa", 
        "americano", 
        "blueberry", 
        "bumblebee", 
        "computer", 
        "grapefruit",
        "grasshopper", 
        "hey google", 
        "hey siri", 
        "jarvis", 
        "ok google", 
        "picovoice", 
        "porcupine", 
        "terminator"
    ]
