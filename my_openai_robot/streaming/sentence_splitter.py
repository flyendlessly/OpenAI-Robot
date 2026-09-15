"""Intelligent sentence splitter for streaming LLM text output."""
from __future__ import annotations

import re
from typing import Generator, Iterable, Iterator, List, Optional

from ..logger import get_logger

logger = get_logger("streaming.sentence_splitter")


class SentenceSplitter:
    """智能断句器：将输入的 Token 流动态切分为适合 TTS 合成的完整自然分句。

    优化策略：
    1. 首句加速（First Sentence Acceleration）：
       第一句遇到弱停顿标点（如逗号、顿号、分号）且字符数达到 min_first_len 时立即切出，
       使扬声器以最快速度发出第一个音节，极大降低首字/首音延迟 (TTFT)。
    2. 后续语义平滑（Semantic Smoothing）：
       后续句子按强停顿标点（句号、问号、感叹号、换行）优先切分；
       若句子过长（达到 max_len）但在弱停顿标点处，也会及时切断，避免单次 TTS 合成耗时过长。
    3. 流结束刷新（Flush on End）：
       流结束时将缓冲区内剩余的所有文本作为一个分句输出。
    """

    # 强断句标点：表示完整句子结束
    STRONG_PUNCTUATION = re.compile(r"[\n\r。！？!?；;]")
    # 弱断句标点：短语停顿
    WEAK_PUNCTUATION = re.compile(r"[，,、]")

    def __init__(
        self,
        *,
        min_first_len: int = 4,
        min_chunk_len: int = 8,
        max_chunk_len: int = 35,
    ) -> None:
        """
        Args:
            min_first_len: 首句触发切分的最小字符数（遇到任意标点即切）
            min_chunk_len: 常规句子遇到弱标点时允许切分的最小长度
            max_chunk_len: 超过该长度时遇到弱标点强制切分
        """
        self.min_first_len = min_first_len
        self.min_chunk_len = min_chunk_len
        self.max_chunk_len = max_chunk_len
        self._buffer: str = ""
        self._is_first_sentence: bool = True

    def reset(self) -> None:
        """重置断句器状态"""
        self._buffer = ""
        self._is_first_sentence = True

    def process_token(self, token: str) -> Iterator[str]:
        """接收单个 Token 增量，若满足切句条件则产出一个或多个分句"""
        if not token:
            return

        self._buffer += token

        while True:
            cut_idx = self._find_split_point()
            if cut_idx is None:
                break

            # 提取切出的句子
            sentence = self._buffer[:cut_idx].strip()
            self._buffer = self._buffer[cut_idx:].lstrip()

            if sentence:
                self._is_first_sentence = False
                logger.debug("SentenceSplitter yielded chunk (first=%s): %s", not self._is_first_sentence, sentence)
                yield sentence

    def _find_split_point(self) -> Optional[int]:
        """查找当前缓冲区中最优的切分点索引 (包含标点本身)"""
        buf_len = len(self._buffer)
        if buf_len == 0:
            return None

        # 策略 1: 首句快速出声
        if self._is_first_sentence:
            for i, ch in enumerate(self._buffer):
                if self.STRONG_PUNCTUATION.match(ch) or self.WEAK_PUNCTUATION.match(ch):
                    if i + 1 >= self.min_first_len:
                        return i + 1
                    # 如果到了强标点，即使字数稍短也切分
                    if self.STRONG_PUNCTUATION.match(ch) and i + 1 >= 2:
                        return i + 1
            return None

        # 策略 2: 后续句子处理
        # 2.1 检查强标点（优先）
        for i, ch in enumerate(self._buffer):
            if self.STRONG_PUNCTUATION.match(ch):
                if i + 1 >= self.min_chunk_len or i + 1 >= 4:
                    return i + 1

        # 2.2 如果缓冲区过长（超过 max_chunk_len），遇到弱标点就切
        if buf_len >= self.max_chunk_len:
            for i, ch in enumerate(self._buffer):
                if self.WEAK_PUNCTUATION.match(ch) and (i + 1 >= self.min_chunk_len):
                    return i + 1

            # 2.3 如果超过 1.5 倍 max_chunk_len 且一直没有标点（如长英文或代码），在空格或中文字符处强制切分
            if buf_len >= int(self.max_chunk_len * 1.5):
                # 寻找最近的空格
                space_idx = self._buffer.rfind(" ", self.min_chunk_len, self.max_chunk_len)
                if space_idx != -1:
                    return space_idx + 1
                # 找不到空格直接截断
                return self.max_chunk_len

        return None

    def flush(self) -> Iterator[str]:
        """流结束时调用，清空并产出缓冲区中剩余的全部文本"""
        remaining = self._buffer.strip()
        self._buffer = ""
        self._is_first_sentence = True
        if remaining:
            logger.debug("SentenceSplitter flushed final chunk: %s", remaining)
            yield remaining

    def split_stream(self, token_stream: Iterable[str]) -> Generator[str, None, None]:
        """高级生成器：直接将 Token 流转换为分句流"""
        self.reset()
        for token in token_stream:
            for sentence in self.process_token(token):
                yield sentence
        for sentence in self.flush():
            yield sentence
