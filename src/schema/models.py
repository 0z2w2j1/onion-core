from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    MAX_STEPS = "max_steps"
    CANCELLED = "cancelled"
    ERROR = "error"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    role: MessageRole
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None

    model_config = {"extra": "allow"}

    @field_validator("content")
    @classmethod
    def content_not_empty_str(cls, v: str | None) -> str | None:
        if v is not None and not isinstance(v, str):
            raise ValueError("content must be a string or None")
        return v


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


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason = FinishReason.STOP
    usage: UsageStats | None = None
    model: str | None = None
    latency_ms: float = 0.0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

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
    stop_sequences: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
