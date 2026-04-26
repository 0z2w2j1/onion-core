"""
Onion Core - 核心数据模型定义

包含 Agent Runtime、Pipeline、Middleware 所需的所有数据类型。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from .error_codes import ErrorCode


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 状态与动作枚举
# ═══════════════════════════════════════════════════════════════════════════════

class AgentStatus(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"


class ActionType(StrEnum):
    REASON = "reason"
    ACT = "act"
    FINISH = "finish"
    ERROR = "error"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    MAX_STEPS = "max_steps"
    CANCELLED = "cancelled"
    ERROR = "error"


# ═══════════════════════════════════════════════════════════════════════════════
# 异常基类
# ═══════════════════════════════════════════════════════════════════════════════

class OnionError(Exception):
    is_fatal: bool = True
    error_code: ErrorCode | None = None

    def __init__(
        self,
        message: str = "",
        *,
        error_code: ErrorCode | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code


class SecurityException(OnionError):
    is_fatal: bool = True

    def __init__(
        self,
        message: str = "",
        *,
        error_code: ErrorCode | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code)


class RateLimitExceeded(OnionError):
    is_fatal: bool = True

    def __init__(
        self,
        message: str = "",
        *,
        error_code: ErrorCode | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code)


class ProviderError(OnionError):
    is_fatal: bool = False

    def __init__(
        self,
        message: str = "",
        *,
        error_code: ErrorCode | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code)


class CircuitBreakerError(OnionError):
    is_fatal: bool = False


class ValidationError(OnionError):
    is_fatal: bool = True

    def __init__(
        self,
        message: str = "",
        *,
        error_code: ErrorCode | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code)


class CacheHitException(OnionError):
    def __init__(self, cached_response: LLMResponse) -> None:
        self.cached_response = cached_response
        super().__init__("Cache hit - returning cached response")


# ═══════════════════════════════════════════════════════════════════════════════
# CircuitBreaker & RetryPolicy
# ═══════════════════════════════════════════════════════════════════════════════

class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RetryOutcome(StrEnum):
    RETRY = "retry"
    FALLBACK = "fallback"
    FATAL = "fatal"


class RetryPolicy:
    _FATAL_TYPES = (
        ValueError, TypeError, NotImplementedError,
        AttributeError, KeyError, IndexError,
    )
    _FALLBACK_TYPES = (RateLimitExceeded,)

    def classify(self, exc: Exception) -> RetryOutcome:
        if isinstance(exc, OnionError):
            retry_outcome: RetryOutcome | None = getattr(exc, "retry_outcome", None)
            if retry_outcome is not None:
                return retry_outcome
            if getattr(exc, "is_fatal", False):
                return RetryOutcome.FATAL
            if isinstance(exc, self._FALLBACK_TYPES):
                return RetryOutcome.FALLBACK
            return RetryOutcome.RETRY
        if isinstance(exc, self._FATAL_TYPES):
            return RetryOutcome.FATAL
        return RetryOutcome.RETRY

    def is_retryable(self, exc: Exception) -> bool:
        return self.classify(exc) == RetryOutcome.RETRY

    def is_fatal(self, exc: Exception) -> bool:
        return self.classify(exc) == RetryOutcome.FATAL

    def is_chain_breaking(self, exc: Exception) -> bool:
        if isinstance(exc, OnionError):
            retry_outcome: RetryOutcome | None = getattr(exc, "retry_outcome", None)
            if retry_outcome is not None:
                return retry_outcome == RetryOutcome.FATAL
            return getattr(exc, "is_fatal", False)
        return self.classify(exc) == RetryOutcome.FATAL


# ═══════════════════════════════════════════════════════════════════════════════
# 消息 & 内容模型
# ═══════════════════════════════════════════════════════════════════════════════

class ImageUrl(BaseModel):
    url: str
    detail: Literal["auto", "low", "high"] = "auto"


class ContentBlock(BaseModel):
    type: Literal["text", "image_url", "image"]
    text: str | None = None
    image_url: ImageUrl | None = None
    source: dict[str, Any] | None = None


class Message(BaseModel):
    role: MessageRole
    content: str | list[ContentBlock] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None

    @property
    def text_content(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return " ".join(
                block.text for block in self.content
                if block.type == "text" and block.text
            )
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# 工具调用
# ═══════════════════════════════════════════════════════════════════════════════

class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("tool call name must not be empty")
        return v.strip()


class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    retry_count: int = 0

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_message(self) -> Message:
        content = self.error if self.is_error else str(self.result)
        return Message(
            role=MessageRole.TOOL,
            content=content,
            name=self.name,
            tool_call_id=self.tool_call_id,
        )


class UsageStats(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# LLM 响应
# ═══════════════════════════════════════════════════════════════════════════════

class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason | None = None
    usage: UsageStats | None = None
    model: str | None = None
    raw: Any | None = None
    latency_ms: float = 0.0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_complete(self) -> bool:
        return self.finish_reason == FinishReason.STOP

    @property
    def is_finished(self) -> bool:
        return self.finish_reason in (
            FinishReason.STOP,
            FinishReason.MAX_STEPS,
            FinishReason.CANCELLED,
        )

    def to_assistant_message(self) -> Message:
        return Message(
            role=MessageRole.ASSISTANT,
            content=self.content,
            tool_calls=self.tool_calls if self.tool_calls else None,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 配置与上下文
# ═══════════════════════════════════════════════════════════════════════════════

class AgentConfig(BaseModel):
    model: str = "gpt-4"
    max_steps: int = Field(default=10, ge=1, le=100)
    max_tokens: int = Field(default=4096, ge=256, le=128000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    system_prompt: str = ""
    tool_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    tool_max_retries: int = Field(default=2, ge=0, le=10)
    memory_max_tokens: int = Field(default=4000, ge=256, le=128000)
    state_max_messages: int = Field(default=200, ge=10, le=10000)
    state_max_history_steps: int = Field(default=100, ge=5, le=5000)
    max_concurrent_tools: int = Field(default=5, ge=1, le=500)
    llm_max_connections: int = Field(default=100, ge=1, le=1000)
    llm_max_keepalive: int = Field(default=20, ge=1, le=200)
    retry_max_attempts: int = Field(default=3, ge=0, le=10)
    retry_min_wait: float = Field(default=1.0, ge=0.1, le=60.0)
    retry_max_wait: float = Field(default=30.0, ge=1.0, le=300.0)
    stop_sequences: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class AgentContext(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    messages: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent State — Runtime 内部状态
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_MAX_MESSAGES = 200
_DEFAULT_MAX_HISTORY_STEPS = 100


class StepRecord(BaseModel):
    step_index: int
    trace_id: str
    action_type: ActionType
    status: AgentStatus
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    llm_response: LLMResponse | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0.0
    token_usage: UsageStats = Field(default_factory=UsageStats)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex[:8]}")
    session_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:8]}")
    status: AgentStatus = AgentStatus.IDLE
    steps: int = Field(default=0, ge=0)
    messages: list[Message] = Field(default_factory=list)
    steps_history: list[StepRecord] = Field(default_factory=list)
    archived_summaries: list[str] = Field(default_factory=list)
    cumulative_usage: UsageStats = Field(default_factory=UsageStats)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            AgentStatus.FINISHED,
            AgentStatus.ERROR,
            AgentStatus.CANCELLED,
        )

    @property
    def is_active(self) -> bool:
        return self.status in (AgentStatus.THINKING, AgentStatus.ACTING)

    @property
    def last_step(self) -> StepRecord | None:
        return self.steps_history[-1] if self.steps_history else None

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        self.updated_at = datetime.now(UTC)

    def add_messages(self, messages: list[Message]) -> None:
        self.messages.extend(messages)
        self.updated_at = datetime.now(UTC)

    def increment_step(self) -> int:
        self.steps += 1
        self.updated_at = datetime.now(UTC)
        return self.steps

    def record_step(self, step: StepRecord) -> None:
        self.steps_history.append(step)
        if step.token_usage:
            self.cumulative_usage.prompt_tokens += step.token_usage.prompt_tokens
            self.cumulative_usage.completion_tokens += step.token_usage.completion_tokens
            self.cumulative_usage.total_tokens += step.token_usage.total_tokens
        self.updated_at = datetime.now(UTC)

    def set_status(self, status: AgentStatus) -> None:
        self.status = status
        self.updated_at = datetime.now(UTC)

    def to_system_message(self, content: str) -> Message:
        return Message(role=MessageRole.SYSTEM, content=content)

    def to_user_message(self, content: str) -> Message:
        return Message(role=MessageRole.USER, content=content)

    def compress(self, config: AgentConfig) -> int:
        max_messages = getattr(config, "state_max_messages", _DEFAULT_MAX_MESSAGES)
        removed = 0
        if len(self.messages) > max_messages:
            overflow = len(self.messages) - max_messages
            system_msgs = [m for m in self.messages if m.role == MessageRole.SYSTEM]
            non_system = [m for m in self.messages if m.role != MessageRole.SYSTEM]
            recent = non_system[max(overflow, len(non_system) - max_messages + len(system_msgs)):]
            self.messages = system_msgs + recent
            removed = len(non_system) - len(recent)
        if removed > 0:
            self.updated_at = datetime.now(UTC)
        return removed

    def archive_history(self, config: AgentConfig) -> int:
        max_steps = getattr(config, "state_max_history_steps", _DEFAULT_MAX_HISTORY_STEPS)
        archived = 0
        if len(self.steps_history) > max_steps:
            overflow = len(self.steps_history) - max_steps
            old = self.steps_history[:overflow]
            for sr in old:
                self.archived_summaries.append(
                    f"[step {sr.step_index}] {sr.action_type.value}: {sr.duration_ms:.0f}ms"
                )
            self.steps_history = self.steps_history[overflow:]
            archived = len(old)
        if archived > 0:
            self.updated_at = datetime.now(UTC)
        return archived

    def compact(self, config: AgentConfig) -> dict[str, int]:
        return {
            "messages_removed": self.compress(config),
            "history_archived": self.archive_history(config),
        }

    def diagnose(self) -> dict[str, int]:
        total_chars = sum(len(m.content or "") for m in self.messages if isinstance(m.content, str))
        return {
            "message_count": len(self.messages),
            "history_count": len(self.steps_history),
            "archive_count": len(self.archived_summaries),
            "total_chars": total_chars,
        }

    def clone(self) -> AgentState:
        return self.model_copy(deep=True)

    def snapshot(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ═══════════════════════════════════════════════════════════════════════════════
# 流式 & 事件
# ═══════════════════════════════════════════════════════════════════════════════

class StreamChunk(BaseModel):
    delta: str = ""
    tool_call_delta: dict[str, Any] | None = None
    finish_reason: FinishReason | None = None
    index: int = 0


class MiddlewareEvent(StrEnum):
    ON_REQUEST = "on_request"
    ON_RESPONSE = "on_response"
    ON_STREAM_CHUNK = "on_stream_chunk"
    ON_ERROR = "on_error"
    ON_TOOL_CALL = "on_tool_call"
    ON_TOOL_RESULT = "on_tool_result"
