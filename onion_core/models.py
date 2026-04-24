"""
Onion Core - 核心数据模型定义
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant", "tool"]


# ── 异常基类（统一定义，避免字符串名称判断的脆弱性）────────────────────────────

class OnionError(Exception):
    """Onion Core 所有异常的基类。"""


class SecurityException(OnionError):
    """安全策略拦截异常（链路中断，不可重试）。"""
    is_fatal: bool = True


class RateLimitExceeded(OnionError):
    """限流异常（链路中断，不可重试）。"""
    is_fatal: bool = True


class ProviderError(OnionError):
    """Provider 调用失败（可重试）。"""
    is_fatal: bool = False


class CircuitBreakerError(OnionError):
    """熔断器异常：当 Provider 处于熔断状态时抛出。"""
    is_fatal: bool = False


class ValidationError(OnionError):
    """输入验证失败异常（不可重试）。"""
    is_fatal: bool = True


# ── 带错误码的异常（向后兼容扩展）────────────────────────────────────────────
#  原有 OnionError 子类保持不变，新增 OnionErrorWithCode 供新代码使用。
#  Pipeline 中通过 RetryPolicy.classify() 统一判断重试策略。
#  注意：error_codes 模块通过 TYPE_CHECKING 避免循环导入，此处不主动导入。

# ── CircuitBreaker 状态 ──────────────────────────────────────────────────────

class CircuitState(StrEnum):
    """熔断器状态枚举。"""
    CLOSED = "closed"        # 正常：请求通过
    OPEN = "open"            # 熔断：请求直接拒绝
    HALF_OPEN = "half_open"  # 半开：允许少量请求测试恢复情况


# ── RetryPolicy ──────────────────────────────────────────────────────────────

class RetryOutcome(StrEnum):
    """重试决策结果。"""
    RETRY = "retry"          # 可重试（网络/超时类）
    FALLBACK = "fallback"    # 不可重试但可 Fallback（限流/服务不可用）
    FATAL = "fatal"          # 彻底失败，立即抛出（业务逻辑/安全拦截）


class RetryPolicy:
    """
    重试决策器：明确区分三种异常处置策略。

    - FATAL:    OnionError.is_fatal=True，或 ValueError/TypeError 等编程错误
                → 立即抛出，不重试，不 Fallback
    - FALLBACK: RateLimitExceeded 等服务层错误
                → 跳过当前 provider，尝试 Fallback
    - RETRY:    网络超时、连接错误等瞬时故障
                → 指数退避重试当前 provider

    用法：
        policy = RetryPolicy()
        outcome = policy.classify(exc)
    """

    # 直接判 FATAL 的内建异常类型（不依赖字符串名称）
    _FATAL_TYPES = (
        ValueError, TypeError, NotImplementedError,
        AttributeError, KeyError, IndexError,
    )

    # 直接判 FALLBACK 的 OnionError 子类
    _FALLBACK_TYPES = (RateLimitExceeded,)

    def classify(self, exc: Exception) -> RetryOutcome:
        """对异常进行三分类。"""
        # OnionError 子类：按 is_fatal 标志位判断
        if isinstance(exc, OnionError):
            if getattr(exc, "is_fatal", False):
                return RetryOutcome.FATAL
            if isinstance(exc, self._FALLBACK_TYPES):
                return RetryOutcome.FALLBACK
            return RetryOutcome.RETRY

        # 内建编程错误：直接 FATAL
        if isinstance(exc, self._FATAL_TYPES):
            return RetryOutcome.FATAL

        # asyncio 超时、连接错误等：RETRY
        return RetryOutcome.RETRY

    def is_retryable(self, exc: Exception) -> bool:
        return self.classify(exc) == RetryOutcome.RETRY

    def is_fatal(self, exc: Exception) -> bool:
        return self.classify(exc) == RetryOutcome.FATAL

    def is_chain_breaking(self, exc: Exception) -> bool:
        """链路中断：FATAL 或来自 OnionError（安全/限流拦截）。"""
        if isinstance(exc, OnionError):
            return True
        return self.classify(exc) == RetryOutcome.FATAL


class FinishReason(StrEnum):
    """LLM 响应结束原因枚举。"""
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class ImageUrl(BaseModel):
    """图片 URL 内容块（OpenAI vision 格式）。"""
    url: str
    detail: Literal["auto", "low", "high"] = "auto"


class ContentBlock(BaseModel):
    """多模态内容块，支持文本和图片。"""
    type: Literal["text", "image_url", "image"]
    text: str | None = None
    image_url: ImageUrl | None = None
    # Anthropic base64 图片
    source: dict[str, Any] | None = None


class Message(BaseModel):
    """
    单条对话消息。

    content 支持纯文本（str）或多模态内容块列表（List[ContentBlock]），
    兼容 OpenAI vision 和 Anthropic multimodal API。
    """
    role: MessageRole
    content: str | list[ContentBlock]
    name: str | None = None

    @property
    def text_content(self) -> str:
        """提取纯文本内容，用于关键词检测等文本处理场景。"""
        if isinstance(self.content, str):
            return self.content
        return " ".join(
            block.text for block in self.content
            if block.type == "text" and block.text
        )


class AgentContext(BaseModel):
    """贯穿整个中间件生命周期的上下文对象。"""
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    messages: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """LLM 发起的工具调用请求。"""
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具执行结果。"""
    tool_call_id: str
    name: str
    result: str | dict[str, Any] | list[Any] | None = None
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


class UsageStats(BaseModel):
    """Token 用量统计。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """LLM 调用的标准化响应。"""
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason | None = None
    usage: UsageStats | None = None
    model: str | None = None
    raw: Any | None = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_complete(self) -> bool:
        return self.finish_reason == FinishReason.STOP


class StreamChunk(BaseModel):
    """流式响应的单个数据块。"""
    delta: str = ""
    tool_call_delta: dict[str, Any] | None = None
    finish_reason: FinishReason | None = None
    index: int = 0


class MiddlewareEvent(StrEnum):
    """中间件生命周期事件类型。"""
    ON_REQUEST = "on_request"
    ON_RESPONSE = "on_response"
    ON_STREAM_CHUNK = "on_stream_chunk"
    ON_ERROR = "on_error"
    ON_TOOL_CALL = "on_tool_call"
    ON_TOOL_RESULT = "on_tool_result"
