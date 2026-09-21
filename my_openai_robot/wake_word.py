"""Wake word detection module supporting Sherpa-ONNX (offline, open-source)."""
# 唤醒词检测模块：支持开源离线 Sherpa-ONNX 唤醒词引擎
from __future__ import annotations

import io
import os
import struct
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any, List, Optional, Protocol, Tuple

try:
    import numpy as np
except ImportError:
    np = None

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

from .config import WakeWordSettings
from .logger import get_logger

logger = get_logger("wake_word")

# 预训练 Sherpa-ONNX 中文 Zipformer 唤醒词模型下载地址
SHERPA_KWS_MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2"
SHERPA_KWS_MODEL_MIRROR_URL = "https://ghproxy.net/https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2"

# 常用中文唤醒词静态音素映射表（零依赖开箱即用，无需安装 pypinyin）
# 支持一个词配置多个发音音调变体（如轻声 vs 本调），显著提高自然口语唤醒率
BUILTIN_KEYWORD_PHONEMES: dict[str, list[str]] = {
    "你好小智": ["n ǐ h ǎo x iǎo zh ì @你好小智"],
    "小智小智": ["x iǎo zh ì x iǎo zh ì @小智小智"],
    "小智": ["x iǎo zh ì @小智"],
    "小爱同学": ["x iǎo ài t óng x ué @小爱同学"],
    "你好问问": ["n ǐ h ǎo w èn w èn @你好问问"],
    "管家你好": ["g uǎn j iā n ǐ h ǎo @管家你好"],
    "芝麻开门": [
        "zh ī m á k āi m én @芝麻开门",  # 口语本调二声（核心高命中率）
        "zh ī m a k āi m én @芝麻开门",  # 词典轻声变体容错
    ],
}


class WakeWordDetector(Protocol):
    """唤醒词检测器通用协议规范"""

    sample_rate: int
    frame_length: int

    def process_audio(self, audio_frame: bytes) -> tuple[bool, int]:
        """
        处理音频帧

        Args:
            audio_frame: PCM 音频数据（16-bit 单声道）

        Returns:
            (是否检测到唤醒词, 唤醒词在配置列表中的索引；若未检测到返回 -1)
        """
        ...

    def reset(self) -> None:
        """重置音频流解码状态"""
        ...

    def close(self) -> None:
        """释放检测器占用的资源"""
        ...


def _convert_chinese_to_kws_lines(text: str) -> List[str]:
    """将中文唤醒词文本动态转为 Sherpa-ONNX 拼音音素标注行（支持本调与轻声多变体）"""
    clean_text = text.strip()
    if not clean_text:
        return []

    if clean_text in BUILTIN_KEYWORD_PHONEMES:
        return list(BUILTIN_KEYWORD_PHONEMES[clean_text])

    try:
        from pypinyin import pinyin
        from pypinyin.contrib.tone_convert import to_finals_tone, to_initials
    except ImportError:
        logger.warning(
            "未安装 pypinyin，无法将自定义唤醒词 '%s' 自动转为拼音。请运行: pip install pypinyin",
            clean_text,
        )
        return []

    variants: List[str] = []

    # 策略 1: 逐字本调发音（如“芝麻开门”中“麻”取单字本调 má，最符合国人口语）
    char_tokens: List[str] = []
    for ch in clean_text:
        py_list = pinyin(ch)
        if py_list and py_list[0]:
            py = py_list[0][0]
            ini = to_initials(py, strict=False)
            fin = to_finals_tone(py, strict=False)
            parts = []
            if ini:
                parts.append(ini)
            if fin:
                parts.append(fin)
            char_tokens.append(" ".join(parts))
    if len(char_tokens) == len(clean_text):
        variants.append(" ".join(char_tokens))

    # 策略 2: 整词连读发音（包含词典规则决定的轻声变调等）
    word_tokens: List[str] = []
    for py_item in pinyin(clean_text):
        if py_item:
            py = py_item[0]
            ini = to_initials(py, strict=False)
            fin = to_finals_tone(py, strict=False)
            parts = []
            if ini:
                parts.append(ini)
            if fin:
                parts.append(fin)
            word_tokens.append(" ".join(parts))
    if len(word_tokens) == len(clean_text):
        variants.append(" ".join(word_tokens))

    # 去重并生成 @clean_text 标注行
    unique_variants = list(dict.fromkeys(variants))
    return [f"{v} @{clean_text}" for v in unique_variants if v.strip()]


def ensure_sherpa_model(model_dir: Path, auto_download: bool = True) -> Path:
    """
    检查并确保 Sherpa-ONNX 唤醒词模型存在；若缺失且开启 auto_download，则自动拉取解压。

    Args:
        model_dir: 模型存放目录
        auto_download: 当模型不存在时是否自动下载

    Returns:
        包含模型文件的实际目录 Path
    """
    # 检查目标目录是否已有关键文件
    if model_dir.exists() and (model_dir / "tokens.txt").exists():
        return model_dir

    # 检查父目录是否有解压后的同名子目录
    candidate_sub = model_dir / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
    if candidate_sub.exists() and (candidate_sub / "tokens.txt").exists():
        return candidate_sub

    if not auto_download:
        raise FileNotFoundError(
            f"未找到 Sherpa-ONNX 唤醒词模型: {model_dir}。\n"
            f"请运行: python -m my_openai_robot.wake_word --download-model 进行一键下载。"
        )

    logger.info("未检测到唤醒词模型，正在自动下载预训练模型 (约 30MB)...")
    print("\n[*] 正在自动下载预训练 Sherpa-ONNX 中文唤醒词模型...")
    parent_dir = model_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    urls = [SHERPA_KWS_MODEL_URL, SHERPA_KWS_MODEL_MIRROR_URL]
    download_success = False
    last_error: Optional[Exception] = None

    # 获取系统代理支持
    proxy_handler = urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(proxy_handler)

    for url in urls:
        try:
            print(f"正在从 {url} 下载...")
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "my-openai-robot/1.0"},
            )
            with opener.open(req, timeout=60) as resp:
                data = resp.read()
                print(f"[OK] 下载完成 ({len(data) // 1024 // 1024} MB)，正在解压模型...")
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as tar:
                    tar.extractall(path=parent_dir)
                download_success = True
                break
        except Exception as exc:
            logger.warning("从 %s 下载模型失败: %s", url, exc)
            last_error = exc

    if not download_success:
        raise RuntimeError(
            f"自动下载唤醒词模型失败: {last_error}。\n"
            f"您可以手动下载: {SHERPA_KWS_MODEL_URL} 并解压到 {model_dir}"
        )

    print("[OK] 唤醒词模型就绪！\n")
    if (model_dir / "tokens.txt").exists():
        return model_dir
    if candidate_sub.exists() and (candidate_sub / "tokens.txt").exists():
        return candidate_sub

    return model_dir


class SherpaOnnxWakeWordDetector:
    """基于 k2-fsa/sherpa-onnx 的离线开源唤醒词检测器"""

    def __init__(self, settings: WakeWordSettings):
        if sherpa_onnx is None:
            raise ImportError(
                "sherpa-onnx 未安装。请运行: pip install sherpa-onnx"
            )
        if np is None:
            raise ImportError(
                "numpy 未安装。请运行: pip install numpy"
            )
        if not settings.enabled:
            raise ValueError("唤醒词检测未启用")

        self.settings = settings
        self.sample_rate = 16000
        self.frame_length = 512  # 32ms 每帧，与标准录音保持一致，延迟低

        # 确保模型存在
        model_dir = ensure_sherpa_model(settings.model_dir, auto_download=True)

        tokens_path = model_dir / "tokens.txt"
        if not tokens_path.exists():
            raise FileNotFoundError(f"未找到 tokens.txt: {tokens_path}")

        # 寻找 encoder / decoder / joiner onnx 文件（优先选择 int8 或标准 onnx）
        encoder_path = self._find_model_file(model_dir, "encoder")
        decoder_path = self._find_model_file(model_dir, "decoder")
        joiner_path = self._find_model_file(model_dir, "joiner")

        # 生成或加载 keywords.txt
        keywords_file = self._prepare_keywords_file(model_dir)

        logger.info(
            "初始化 Sherpa-ONNX 唤醒词检测器: keywords=%s, score=%.2f, threshold=%.2f, threads=%d",
            settings.keywords,
            settings.keywords_score,
            settings.keywords_threshold,
            settings.num_threads,
        )

        try:
            self.spotter = sherpa_onnx.KeywordSpotter(
                tokens=str(tokens_path),
                encoder=str(encoder_path),
                decoder=str(decoder_path),
                joiner=str(joiner_path),
                keywords_file=str(keywords_file),
                num_threads=settings.num_threads,
                sample_rate=int(self.sample_rate),
                keywords_score=settings.keywords_score,
                keywords_threshold=settings.keywords_threshold,
            )
            self.stream = self.spotter.create_stream()
        except Exception as exc:
            raise RuntimeError(f"初始化 Sherpa-ONNX KeywordSpotter 失败: {exc}")

    def _find_model_file(self, model_dir: Path, prefix: str) -> Path:
        """在模型目录中检索指定前缀的模型文件"""
        files = list(model_dir.glob(f"{prefix}*.onnx"))
        if not files:
            raise FileNotFoundError(f"在 {model_dir} 中未找到 {prefix}*.onnx 模型文件")
        # 如果有 int8 模型优先使用以节省树莓派或桌面内存
        int8_files = [f for f in files if "int8" in f.name]
        return int8_files[0] if int8_files else files[0]

    def _prepare_keywords_file(self, model_dir: Path) -> Path:
        """准备唤醒词定义文件 keywords.txt"""
        if self.settings.keywords_file and self.settings.keywords_file.exists():
            return self.settings.keywords_file

        generated_lines = []
        for kw in self.settings.keywords:
            lines = _convert_chinese_to_kws_lines(kw)
            if lines:
                generated_lines.extend(lines)
            else:
                logger.warning("唤醒词 '%s' 无法解析为有效拼音音素，可能影响触发效果", kw)

        if not generated_lines:
            # 如果没有生成成功，检查模型自带的 keywords.txt
            builtin_kw = model_dir / "keywords.txt"
            if builtin_kw.exists():
                logger.info("使用模型自带默认 keywords.txt: %s", builtin_kw)
                return builtin_kw
            raise ValueError(f"无法为唤醒词列表 {self.settings.keywords} 生成拼音音素配置")

        # 写入临时/自动生成的关键词文件
        cache_kw_file = model_dir / "keywords_auto.txt"
        cache_kw_file.write_text("\n".join(generated_lines) + "\n", encoding="utf-8")
        return cache_kw_file

    def process_audio(self, audio_frame: Any) -> tuple[bool, int]:
        """
        处理音频帧

        Args:
            audio_frame: PCM 16-bit 单声道音频数据（支持 bytes、bytearray、CFFI buffer 等）

        Returns:
            (是否检测到唤醒词, 关键词索引)
        """
        if audio_frame is None or self.spotter is None or self.stream is None:
            return False, -1

        if not isinstance(audio_frame, (bytes, bytearray)):
            try:
                audio_frame = bytes(audio_frame)
            except Exception:
                pass

        if len(audio_frame) == 0:
            return False, -1

        # 将 16-bit PCM 字节转为 float32 归一化数组 [-1.0, 1.0]
        samples = np.frombuffer(audio_frame, dtype=np.int16).astype(np.float32) / 32768.0

        self.stream.accept_waveform(self.sample_rate, samples)
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)

        result = self.spotter.get_result(self.stream)
        if result:
            # 检测到了唤醒词，立即重置流以防重复触发
            self.spotter.reset_stream(self.stream)

            # 匹配对应配置唤醒词索引
            matched_idx = -1
            for i, kw in enumerate(self.settings.keywords):
                if kw in result or result in kw:
                    matched_idx = i
                    break
            if matched_idx == -1:
                matched_idx = 0

            logger.info("⚡ [Sherpa-ONNX] 检测到唤醒词: '%s' (匹配索引=%d)", result, matched_idx)
            return True, matched_idx

        return False, -1

    def reset(self) -> None:
        """重置音频流状态"""
        if self.spotter and self.stream:
            try:
                self.spotter.reset_stream(self.stream)
            except Exception:
                pass

    def close(self) -> None:
        """释放资源"""
        self.stream = None
        self.spotter = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_wake_word_detector(settings: WakeWordSettings) -> Optional[WakeWordDetector]:
    """
    唤醒词检测器工厂函数：根据配置实例化 Sherpa-ONNX 离线检测器。

    Args:
        settings: 唤醒词配置

    Returns:
        实现了 WakeWordDetector 协议的实例；若未启用则返回 None
    """
    if not settings.enabled:
        return None

    try:
        return SherpaOnnxWakeWordDetector(settings)
    except Exception as exc:
        logger.error("初始化 Sherpa-ONNX 唤醒词检测器失败: %s", exc)
        print(f"[!] Sherpa-ONNX 唤醒词初始化失败: {exc}")
        return None


def list_builtin_keywords() -> list[str]:
    """列出支持的内置/推荐中文唤醒词"""
    return list(BUILTIN_KEYWORD_PHONEMES.keys()) + [
        "(支持任意中文词，配合 pypinyin 自动转拼音，免重新训练)"
    ]


if __name__ == "__main__":
    if "--download-model" in sys.argv:
        default_dir = Path("data/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01")
        print(f"开始检查并下载预训练 Sherpa-ONNX 模型至: {default_dir} ...")
        res = ensure_sherpa_model(default_dir, auto_download=True)
        print(f"[OK] 模型准备就绪: {res}")
    else:
        print("Sherpa-ONNX 唤醒词模块。可用参数:")
        print("  --download-model   下载预训练轻量中文唤醒词模型")
