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
        except getattr(pvporcupine, "PorcupineActivationRefusedError", ()):
            raise RuntimeError(
                "Picovoice AccessKey 激活被拒绝 (Activation Refused)。\n"
                "可能原因：Key 已失效/过期、被吊销或输入有误。\n"
                "请登录 https://console.picovoice.ai/ 获取最新 AccessKey 并更新 .env 中的 PORCUPINE_ACCESS_KEY。"
            )
        except getattr(pvporcupine, "PorcupineActivationLimitError", ()):
            raise RuntimeError(
                "Picovoice 设备授权数已超限 (Device Limit Exceeded)。\n"
                "Picovoice 免费版每月最多允许 3 台不同设备。请在控制台重置或更换账号/Key。"
            )
        except getattr(pvporcupine, "PorcupineActivationThrottledError", ()):
            raise RuntimeError("Picovoice 激活请求过于频繁，请稍后再试。")
        except getattr(pvporcupine, "PorcupineActivationError", ()):
            raise RuntimeError(
                "连接 Picovoice 激活服务器失败，请检查网络或代理设置。"
            )
        except getattr(pvporcupine, "PorcupineInvalidArgumentError", ()) as e:
            err_msg = str(e)
            if "AccessKey" in err_msg:
                raise RuntimeError(
                    f"Picovoice AccessKey 格式不正确或未完整复制。\n"
                    f"请登录 https://console.picovoice.ai/ 复制顶部完整的 AccessKey（通常为较长的 Base64 字符串，末尾常带有等号）。"
                )
            raise RuntimeError(
                f"唤醒词或模型参数无效: {e}\n当前配置的唤醒词为: {settings.keywords}。请使用 --list-wake-words 查看内置支持词。"
            )
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
