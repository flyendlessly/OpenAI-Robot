"""Child safety content filtering module - 儿童内容安全过滤模块（企业级三层防护）"""
# 为儿童用户提供多层内容安全保护：本地黑名单 + Prompt 引导 + Azure 过滤器
from __future__ import annotations

import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol

from .config import ChildSafetySettings


class ContentFilterResult:
    """内容过滤结果"""
    
    def __init__(
        self,
        is_safe: bool,
        reason: str = "",
        filter_layer: str = "",
        matched_keywords: list[str] | None = None,
        azure_filter_details: dict | None = None,
    ):
        self.is_safe = is_safe
        self.reason = reason
        self.filter_layer = filter_layer  # local_blacklist / system_prompt / azure_filter
        self.matched_keywords = matched_keywords or []
        self.azure_filter_details = azure_filter_details or {}
    
    def __repr__(self) -> str:
        return f"ContentFilterResult(is_safe={self.is_safe}, layer={self.filter_layer}, reason={self.reason})"


class LocalBlacklist:
    """本地敏感词黑名单管理器"""
    
    def __init__(self, blacklist_path: Path):
        self.blacklist_path = blacklist_path
        self.keywords: set[str] = set()
        self.patterns: list[re.Pattern] = []
        self._load_blacklist()
    
    def _load_blacklist(self) -> None:
        """加载黑名单词库"""
        if not self.blacklist_path.exists():
            print(f"⚠ 黑名单文件不存在: {self.blacklist_path}，将使用内置基础词库")
            self._load_builtin_blacklist()
            return
        
        try:
            with open(self.blacklist_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    
                    # 支持正则表达式（以 / 开头和结尾）
                    if line.startswith("/") and line.endswith("/"):
                        pattern_str = line[1:-1]
                        try:
                            self.patterns.append(re.compile(pattern_str, re.IGNORECASE))
                        except re.error as e:
                            print(f"⚠ 无效正则表达式: {line} - {e}")
                    else:
                        self.keywords.add(line.lower())
            
            print(f"✓ 已加载 {len(self.keywords)} 个关键词，{len(self.patterns)} 个正则规则")
        except Exception as e:
            print(f"✗ 加载黑名单失败: {e}，使用内置基础词库")
            self._load_builtin_blacklist()
    
    def _load_builtin_blacklist(self) -> None:
        """加载内置基础黑名单"""
        builtin_keywords = [
            # 暴力类
            "杀人", "杀死", "谋杀", "自杀", "血腥", "暴力", "打人", "杀害",
            "枪支", "炸弹", "武器", "爆炸", "恐怖袭击",
            # 色情类
            "色情", "裸体", "性交", "成人内容", "黄色",
            # 脏话类
            "妈的", "操", "他妈", "傻逼", "草泥马", "艹",
            # 恐怖类
            "恐怖", "鬼故事", "吓人", "血淋淋",
            # 毒品赌博
            "毒品", "海洛因", "赌博", "吸毒",
        ]
        self.keywords = set(word.lower() for word in builtin_keywords)
        print(f"✓ 已加载内置基础词库: {len(self.keywords)} 个关键词")
    
    def check(self, text: str) -> ContentFilterResult:
        """检查文本是否包含敏感词"""
        text_lower = text.lower()
        
        # 检查关键词
        for keyword in self.keywords:
            if keyword in text_lower:
                return ContentFilterResult(
                    is_safe=False,
                    reason="包含不适合儿童的内容",
                    filter_layer="local_blacklist",
                    matched_keywords=[keyword],
                )
        
        # 检查正则规则
        for pattern in self.patterns:
            match = pattern.search(text)
            if match:
                return ContentFilterResult(
                    is_safe=False,
                    reason="内容不适合儿童",
                    filter_layer="local_blacklist",
                    matched_keywords=[match.group(0)],
                )
        
        return ContentFilterResult(is_safe=True, filter_layer="local_blacklist")


class AzureContentFilterChecker:
    """Azure 内容过滤器结果检查"""
    
    def __init__(self, filter_level: str = "strict"):
        """
        Args:
            filter_level: 过滤级别 low/medium/strict
                - low: 只拦截高危内容 (severity >= 6)
                - medium: 拦截中高危内容 (severity >= 4)
                - strict: 拦截所有疑似内容 (severity >= 2)
        """
        self.filter_level = filter_level
        self.thresholds = {
            "low": 6,
            "medium": 4,
            "strict": 2,
        }
    
    def check_response(self, response_data: dict) -> ContentFilterResult:
        """检查 Azure OpenAI 响应中的内容过滤结果
        
        Args:
            response_data: OpenAI API 返回的完整响应字典
        
        Returns:
            ContentFilterResult: 过滤结果
        """
        # Azure OpenAI 会在 choices[0].finish_reason 返回过滤信息
        # 以及 prompt_filter_results 和 content_filter_results 字段
        
        if not isinstance(response_data, dict):
            return ContentFilterResult(is_safe=True, filter_layer="azure_filter")
        
        # 检查是否因内容过滤而停止
        choices = response_data.get("choices", [])
        if choices:
            finish_reason = choices[0].get("finish_reason")
            if finish_reason == "content_filter":
                return ContentFilterResult(
                    is_safe=False,
                    reason="Azure 内容过滤器检测到不适合内容",
                    filter_layer="azure_filter",
                    azure_filter_details={"finish_reason": finish_reason},
                )
        
        # 检查详细过滤结果（如果有）
        # 注意：这取决于 Azure 配置，可能不总是返回
        content_filter_results = response_data.get("content_filter_results", {})
        if content_filter_results:
            threshold = self.thresholds.get(self.filter_level, 2)
            
            categories = ["hate", "self_harm", "sexual", "violence"]
            for category in categories:
                category_result = content_filter_results.get(category, {})
                severity = category_result.get("severity", 0)
                
                if severity >= threshold:
                    return ContentFilterResult(
                        is_safe=False,
                        reason=f"检测到{category}类内容（级别: {severity}）",
                        filter_layer="azure_filter",
                        azure_filter_details=content_filter_results,
                    )
        
        return ContentFilterResult(is_safe=True, filter_layer="azure_filter")


class ConversationLogger:
    """对话日志记录器（供家长审查）"""
    
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def log_conversation(
        self,
        user_input: str,
        assistant_response: str,
        filter_results: list[ContentFilterResult],
        metadata: dict | None = None,
    ) -> None:
        """记录一次对话"""
        timestamp = datetime.now()
        log_file = self.log_dir / f"{timestamp.strftime('%Y-%m-%d')}.jsonl"
        
        entry = {
            "timestamp": timestamp.isoformat(),
            "user_input": user_input,
            "assistant_response": assistant_response,
            "filter_results": [
                {
                    "is_safe": r.is_safe,
                    "reason": r.reason,
                    "layer": r.filter_layer,
                    "matched_keywords": r.matched_keywords,
                }
                for r in filter_results
            ],
            "metadata": metadata or {},
        }
        
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"⚠ 记录对话日志失败: {e}")


class ChildSafetyFilter:
    """儿童内容安全过滤器（三层防护）"""
    
    def __init__(self, settings: ChildSafetySettings):
        self.settings = settings
        
        # 第 1 层：本地黑名单
        self.blacklist: Optional[LocalBlacklist] = None
        if settings.use_local_blacklist:
            self.blacklist = LocalBlacklist(settings.blacklist_path)
        
        # 第 2 层：Azure 内容过滤
        self.azure_checker: Optional[AzureContentFilterChecker] = None
        if settings.enable_azure_content_filter:
            self.azure_checker = AzureContentFilterChecker(settings.filter_level)
        
        # 对话日志
        self.logger: Optional[ConversationLogger] = None
        if settings.log_all_conversations:
            self.logger = ConversationLogger(settings.conversation_log_path)
    
    def check_input(self, user_input: str) -> ContentFilterResult:
        """检查用户输入是否安全（第 1 层）"""
        if self.blacklist:
            result = self.blacklist.check(user_input)
            if not result.is_safe:
                return result
        
        return ContentFilterResult(is_safe=True, filter_layer="input_check")
    
    def check_output(self, assistant_response: str, response_data: dict | None = None) -> ContentFilterResult:
        """检查 AI 输出是否安全（第 3 层）"""
        # 先检查本地黑名单
        if self.blacklist:
            result = self.blacklist.check(assistant_response)
            if not result.is_safe:
                return result
        
        # 再检查 Azure 过滤结果
        if self.azure_checker and response_data:
            result = self.azure_checker.check_response(response_data)
            if not result.is_safe:
                return result
        
        return ContentFilterResult(is_safe=True, filter_layer="output_check")
    
    def get_safe_response(self) -> str:
        """获取安全的替代回复"""
        suggestion = random.choice(self.settings.safe_topics)
        return self.settings.safe_response_template.format(suggestion=suggestion)
    
    def log_conversation(
        self,
        user_input: str,
        assistant_response: str,
        filter_results: list[ContentFilterResult],
        metadata: dict | None = None,
    ) -> None:
        """记录对话（如果启用）"""
        if self.logger:
            self.logger.log_conversation(user_input, assistant_response, filter_results, metadata)
