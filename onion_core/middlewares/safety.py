"""Onion Core - 安全护栏中间件"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Pattern

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, SecurityException, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.safety")


@dataclass
class PiiRule:
    """单条 PII 脱敏规则。"""
    name: str
    pattern: Pattern[str]
    replacement: str = "***"
    description: str = ""


BUILTIN_PII_RULES: List[PiiRule] = [
    PiiRule("email", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[email]", "电子邮件"),
    PiiRule("phone_cn", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "***", "中国大陆手机号"),
    PiiRule("phone_intl", re.compile(r"\+\d{1,3}(?:[-.\s]\d{2,4}){2,4}"), "***", "国际电话（带+区号）"),
    PiiRule("id_card_cn", re.compile(r"\b\d{17}[\dXx]\b"), "[ID]", "中国居民身份证号"),
    PiiRule("credit_card", re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12})\b"), "[CARD]", "信用卡号"),
]

DEFAULT_BLOCKED_KEYWORDS: List[str] = [
    "ignore instructions",
    "ignore previous instructions",
    "system prompt",
    "disregard above",
    "override safety",
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
        blocked_keywords: Optional[List[str]] = None,
        blocked_tools: Optional[List[str]] = None,
        pii_rules: Optional[List[PiiRule]] = None,
        enable_builtin_pii: bool = True,
    ) -> None:
        self._blocked_keywords = [kw.lower() for kw in (blocked_keywords or DEFAULT_BLOCKED_KEYWORDS)]
        self._blocked_tools: set[str] = set(blocked_tools or [])
        self._pii_rules: List[PiiRule] = []
        if enable_builtin_pii:
            self._pii_rules.extend(BUILTIN_PII_RULES)
        if pii_rules:
            self._pii_rules.extend(pii_rules)

    async def startup(self) -> None:
        logger.info(
            "SafetyGuardrailMiddleware started | keywords=%d | pii_rules=%d | blocked_tools=%d",
            len(self._blocked_keywords), len(self._pii_rules), len(self._blocked_tools),
        )

    async def shutdown(self) -> None:
        logger.info("SafetyGuardrailMiddleware stopped.")

    def add_pii_rule(self, rule: PiiRule) -> "SafetyGuardrailMiddleware":
        self._pii_rules.append(rule)
        return self

    def add_blocked_keyword(self, keyword: str) -> "SafetyGuardrailMiddleware":
        self._blocked_keywords.append(keyword.lower())
        return self

    def add_blocked_tool(self, tool_name: str) -> "SafetyGuardrailMiddleware":
        self._blocked_tools.add(tool_name)
        return self

    async def process_request(self, context: AgentContext) -> AgentContext:
        last_user_msg = self._get_last_user_message(context)
        if last_user_msg is None:
            return context
        text_lower = last_user_msg.lower()
        for keyword in self._blocked_keywords:
            if keyword in text_lower:
                logger.warning("[%s] BLOCKED — keyword: '%s'", context.request_id, keyword)
                raise SecurityException(f"Request blocked: detected prohibited keyword '{keyword}'")
        logger.info("[%s] Safety check passed.", context.request_id)
        return context

    async def process_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse:
        if response.content:
            masked = self._mask_pii(response.content)
            if masked != response.content:
                logger.info("[%s] PII masked in response.", context.request_id)
                response = response.model_copy(update={"content": masked})
        return response

    async def process_stream_chunk(self, context: AgentContext, chunk: StreamChunk) -> StreamChunk:
        """
        滑动窗口流式 PII 过滤：
        保持末尾一定长度（_STREAM_BUFFER_SIZE）的缓冲区不输出，
        以确保不会将一个 PII 模式（如手机号）的前半部分先输出。
        """
        buf_key = f"_safety_buf_{context.request_id}"
        full_buf: str = context.metadata.get(buf_key, "") + chunk.delta

        if chunk.finish_reason:
            # 流结束：对剩余缓冲区做完整过滤并输出
            context.metadata.pop(buf_key, None)
            masked = self._mask_pii(full_buf)
            return chunk.model_copy(update={"delta": masked})

        # 中间 chunk：保留末尾缓冲区，输出确认安全的前缀
        if len(full_buf) > self._STREAM_BUFFER_SIZE:
            split_at = len(full_buf) - self._STREAM_BUFFER_SIZE
            safe_prefix = full_buf[:split_at]
            remaining = full_buf[split_at:]

            context.metadata[buf_key] = remaining
            # 对前缀进行脱敏后输出
            return chunk.model_copy(update={"delta": self._mask_pii(safe_prefix)})

        context.metadata[buf_key] = full_buf
        return chunk.model_copy(update={"delta": ""})

    # 缓冲区保留长度：覆盖最长常用 PII 模式
    # 信用卡号最长约 19 位，国际电话含分隔符约 20 字符，身份证 18 位
    # 设为 50 以确保任何单个 PII 模式都不会被截断在边界处
    _STREAM_BUFFER_SIZE = 50

    async def on_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        if tool_call.name in self._blocked_tools:
            logger.warning("[%s] Tool '%s' blocked.", context.request_id, tool_call.name)
            raise SecurityException(f"Tool '{tool_call.name}' is not permitted")
        logger.info("[%s] Tool call '%s' passed.", context.request_id, tool_call.name)
        return tool_call

    async def on_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult:
        if isinstance(result.result, str):
            masked = self._mask_pii(result.result)
            if masked != result.result:
                logger.info("[%s] PII masked in tool result '%s'.", context.request_id, result.name)
                result = result.model_copy(update={"result": masked})
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        logger.error("[%s] Safety middleware error: %s", context.request_id, error)

    @staticmethod
    def _get_last_user_message(context: AgentContext) -> Optional[str]:
        for msg in reversed(context.messages):
            if msg.role == "user":
                return msg.text_content  # 支持多模态 content
        return None

    def _mask_pii(self, text: str) -> str:
        for rule in self._pii_rules:
            text = rule.pattern.sub(rule.replacement, text)
        return text
