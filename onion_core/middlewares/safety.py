"""Onion Core - 安全护栏中间件"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from re import Pattern

from ..base import BaseMiddleware
from ..error_codes import ErrorCode
from ..models import AgentContext, LLMResponse, SecurityException, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.safety")


@dataclass
class PiiRule:
    """单条 PII 脱敏规则。"""
    name: str
    pattern: Pattern[str]
    replacement: str = "***"
    description: str = ""


BUILTIN_PII_RULES: list[PiiRule] = [
    PiiRule("email", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[email]", "电子邮件"),
    PiiRule("phone_cn", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "***", "中国大陆手机号"),
    PiiRule("phone_intl", re.compile(r"\+\d{1,3}(?:[-.\s]\d{2,4}){2,4}"), "***", "国际电话（带+区号）"),
    PiiRule("id_card_cn", re.compile(r"\b\d{17}[\dXx]\b"), "[ID]", "中国居民身份证号"),
    PiiRule("credit_card", re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12})\b"), "[CARD]", "信用卡号"),
]

DEFAULT_BLOCKED_KEYWORDS: list[str] = [
    # English multi-word injection patterns (specific, low false-positive)
    "ignore previous instructions",
    "disregard above",
    "override safety",
    "prompt injection",
    # Chinese keywords
    "绕过安全",
    "越狱",
]

# 预编译的注入检测正则模式（增强检测能力）
INJECTION_PATTERNS: list[Pattern[str]] = [
    re.compile(r"ign\s*ore\s+instr.*ctions", re.IGNORECASE),
    re.compile(r"byp\s*ass\s+sec.*rity", re.IGNORECASE),
    re.compile(r"sys\s*tem\s+prom.*pt", re.IGNORECASE),
    re.compile(r"disregard\s+above", re.IGNORECASE),
    re.compile(r"overrid[e]\s+safet[y]", re.IGNORECASE),
]


class SafetyGuardrailMiddleware(BaseMiddleware):
    """
    安全护栏中间件。priority=200。

    - 输入侧：关键词检测，拦截疑似 prompt injection
    - 输出侧：PII 脱敏（插件式规则）
    - 工具侧：黑名单检查 + 结果 PII 过滤
    """

    priority: int = 200
    is_mandatory: bool = True

    def __init__(
        self,
        blocked_keywords: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        pii_rules: list[PiiRule] | None = None,
        enable_builtin_pii: bool = True,
        enable_input_pii_masking: bool = False,
    ) -> None:
        self._blocked_keywords = list(blocked_keywords or DEFAULT_BLOCKED_KEYWORDS)
        self._keyword_patterns = [
            re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
            for kw in self._blocked_keywords
        ]
        self._blocked_tools: set[str] = set(blocked_tools or [])
        self._enable_input_pii_masking = enable_input_pii_masking
        self._pii_rules: list[PiiRule] = []
        if enable_builtin_pii:
            self._pii_rules.extend(BUILTIN_PII_RULES)
        if pii_rules:
            self._pii_rules.extend(pii_rules)
        # 预编译的注入检测正则模式
        self._injection_patterns = INJECTION_PATTERNS

    async def startup(self) -> None:
        logger.info(
            "SafetyGuardrailMiddleware started | keywords=%d | pii_rules=%d | blocked_tools=%d",
            len(self._blocked_keywords), len(self._pii_rules), len(self._blocked_tools),
        )

    async def shutdown(self) -> None:
        logger.info("SafetyGuardrailMiddleware stopped.")

    def add_pii_rule(self, rule: PiiRule) -> SafetyGuardrailMiddleware:
        self._pii_rules.append(rule)
        return self

    def add_blocked_keyword(self, keyword: str) -> SafetyGuardrailMiddleware:
        self._blocked_keywords.append(keyword)
        self._keyword_patterns.append(
            re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
        )
        return self

    def add_blocked_tool(self, tool_name: str) -> SafetyGuardrailMiddleware:
        self._blocked_tools.add(tool_name)
        return self

    async def process_request(self, context: AgentContext) -> AgentContext:
        last_user_msg = self._get_last_user_message(context)
        if last_user_msg is None:
            return context
        
        # 1. 关键词检测（整词边界匹配，避免误报）
        for keyword, pattern in zip(self._blocked_keywords, self._keyword_patterns, strict=True):
            if pattern.search(last_user_msg):
                logger.warning("[%s] BLOCKED — keyword: '%s'", context.request_id, keyword)
                raise SecurityException(
                    f"Request blocked: detected prohibited keyword '{keyword}'",
                    error_code=ErrorCode.SECURITY_BLOCKED_KEYWORD,
                )
        
        # 2. 正则模式检测（增强检测能力）
        for pattern in self._injection_patterns:
            if pattern.search(last_user_msg):
                logger.warning("[%s] BLOCKED — injection pattern detected", context.request_id)
                raise SecurityException(
                    "Potential prompt injection detected",
                    error_code=ErrorCode.SECURITY_PROMPT_INJECTION,
                )
        
        # 3. Unicode 混淆检测
        if self._detect_unicode_confusion(last_user_msg):
            logger.warning("[%s] BLOCKED — unicode confusion detected", context.request_id)
            raise SecurityException(
                "Suspicious character encoding detected",
                error_code=ErrorCode.SECURITY_PROMPT_INJECTION,
            )
        
        # 4. 输入侧 PII 脱敏（默认关闭，由 enable_input_pii_masking 控制）
        if self._enable_input_pii_masking:
            masked = self._mask_pii(last_user_msg)
            if masked != last_user_msg:
                for i in range(len(context.messages) - 1, -1, -1):
                    msg = context.messages[i]
                    if msg.role == "user" and msg.text_content == last_user_msg:
                        if isinstance(msg.content, str):
                            context.messages[i] = msg.model_copy(update={"content": masked})
                        break
                logger.info("[%s] Input PII masked.", context.request_id)
        
        logger.debug("[%s] Safety check passed.", context.request_id)
        return context

    async def process_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse:
        if response.content:
            masked = self._mask_pii(response.content)
            if masked != response.content:
                logger.debug("[%s] PII masked in response.", context.request_id)
                response = response.model_copy(update={"content": masked})
        return response

    async def process_stream_chunk(self, context: AgentContext, chunk: StreamChunk) -> StreamChunk:
        """
        滑动窗口流式 PII 过滤：
        保持末尾一定长度（_STREAM_BUFFER_SIZE）的缓冲区不输出，
        以确保不会将一个 PII 模式（如手机号）的前半部分先输出。
        
        改进：增加超时强制刷新机制，避免首字延迟（TTFT）过长。
        """
        buf_key = f"_safety_buf_{context.request_id}"
        timestamp_key = f"_safety_buf_ts_{context.request_id}"
        
        now = time.monotonic()
        full_buf: str = context.metadata.get(buf_key, "") + chunk.delta
        buf_start_time = context.metadata.get(timestamp_key, now)
        
        # 强制刷新条件：流结束、缓冲区满、或缓冲超时
        should_flush = (
            chunk.finish_reason is not None or
            len(full_buf) > self._STREAM_BUFFER_SIZE or
            (now - buf_start_time) > self._MAX_BUFFER_AGE
        )
        
        if should_flush:
            # 清理时间戳和缓冲区
            context.metadata.pop(timestamp_key, None)
            masked = self._mask_pii(full_buf)
            context.metadata.pop(buf_key, None)
            return chunk.model_copy(update={"delta": masked})
        
        # 首次写入时记录时间戳
        if buf_key not in context.metadata:
            context.metadata[timestamp_key] = now
        
        context.metadata[buf_key] = full_buf
        return chunk.model_copy(update={"delta": ""})

    # 缓冲区保留长度：覆盖最长常用 PII 模式
    # 信用卡号最长约 19 位，国际电话含分隔符约 20 字符，身份证 18 位
    # 设为 50 以确保任何单个 PII 模式都不会被截断在边界处
    _STREAM_BUFFER_SIZE = 50
    
    # 最大缓冲时间（秒），超过此时间强制刷新以避免首字延迟过长
    _MAX_BUFFER_AGE = 2.0

    async def on_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        if tool_call.name in self._blocked_tools:
            logger.warning("[%s] Tool '%s' blocked.", context.request_id, tool_call.name)
            raise SecurityException(
                f"Tool '{tool_call.name}' is not permitted",
                error_code=ErrorCode.SECURITY_FORBIDDEN_TOOL,
            )
        logger.debug("[%s] Tool call '%s' passed.", context.request_id, tool_call.name)
        return tool_call

    async def on_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult:
        if isinstance(result.result, str):
            masked = self._mask_pii(result.result)
            if masked != result.result:
                logger.debug("[%s] PII masked in tool result '%s'.", context.request_id, result.name)
                result = result.model_copy(update={"result": masked})
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        # 清理流式 PII 缓冲区
        buf_key = f"_safety_buf_{context.request_id}"
        timestamp_key = f"_safety_buf_ts_{context.request_id}"
        context.metadata.pop(buf_key, None)
        context.metadata.pop(timestamp_key, None)
        logger.error("[%s] Safety middleware error: %s", context.request_id, error)

    @staticmethod
    def _get_last_user_message(context: AgentContext) -> str | None:
        for msg in reversed(context.messages):
            if msg.role == "user":
                return msg.text_content  # 支持多模态 content
        return None

    def _mask_pii(self, text: str) -> str:
        for rule in self._pii_rules:
            text = rule.pattern.sub(rule.replacement, text)
        return text
    
    @staticmethod
    def _detect_unicode_confusion(text: str) -> bool:
        """
        检测是否存在 Unicode 混淆攻击。
        
        策略：仅检测 ASCII 字母与非 ASCII 字母的混合使用（homograph attack），
        而非单纯的非 ASCII 字符比例。这样可以避免误报纯中文/日文等合法文本。
        
        真正的混淆攻击通常表现为：在英文单词中混入形似的非 ASCII 字符，
        例如：'раураӏ'（西里尔字母）伪装成 'paypal'。
        
        因此我们检查：
        1. 是否同时包含 ASCII 字母和非 ASCII 字母
        2. 非 ASCII 字母占比超过阈值
        """
        ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
        non_ascii_alpha = sum(1 for c in text if not c.isascii() and c.isalpha())
        total_alpha = ascii_alpha + non_ascii_alpha
        
        # 如果只有非 ASCII 字母（如纯中文），不视为混淆攻击
        if ascii_alpha == 0 or non_ascii_alpha == 0:
            return False
        
        # 当 ASCII 和非 ASCII 字母混合时，检查非 ASCII 比例
        return non_ascii_alpha / total_alpha > 0.3
