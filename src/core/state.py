from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.schema.models import (
    ActionType,
    AgentConfig,
    AgentStatus,
    Message,
    MessageRole,
    StepRecord,
    UsageStats,
)

_DEFAULT_MAX_MESSAGES = 200
_DEFAULT_MAX_HISTORY_STEPS = 100


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
        total_chars = sum(len(m.content or "") for m in self.messages)
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


class StateTransitionError(Exception):
    pass


class StateMachine:
    ALLOWED_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
        AgentStatus.IDLE: {AgentStatus.THINKING},
        AgentStatus.THINKING: {AgentStatus.ACTING, AgentStatus.FINISHED, AgentStatus.ERROR},
        AgentStatus.ACTING: {AgentStatus.THINKING, AgentStatus.FINISHED, AgentStatus.ERROR},
        AgentStatus.FINISHED: set(),
        AgentStatus.ERROR: set(),
        AgentStatus.CANCELLED: set(),
    }

    def __init__(self, state: AgentState):
        self._state = state
        self._listeners: list[Callable[[AgentStatus, AgentStatus], None]] = []

    @property
    def current_status(self) -> AgentStatus:
        return self._state.status

    def transition_to(self, target: AgentStatus) -> AgentState:
        if target == self._state.status:
            return self._state
        if target not in self.ALLOWED_TRANSITIONS.get(self._state.status, set()):
            raise StateTransitionError(
                f"Invalid transition: {self._state.status.value} -> {target.value}"
            )
        previous = self._state.status
        self._state.set_status(target)
        for listener in self._listeners:
            with contextlib.suppress(Exception):
                listener(previous, target)
        return self._state

    def can_transition_to(self, target: AgentStatus) -> bool:
        return target in self.ALLOWED_TRANSITIONS.get(self._state.status, set())

    def on_transition(self, callback: Callable[[AgentStatus, AgentStatus], None]) -> None:
        self._listeners.append(callback)

    def determine_next_action(self, has_tool_calls: bool, llm_finished: bool) -> ActionType:
        if self._state.status == AgentStatus.ERROR or self._state.status == AgentStatus.CANCELLED:
            return ActionType.ERROR
        if llm_finished and not has_tool_calls:
            return ActionType.FINISH
        if has_tool_calls:
            return ActionType.ACT
        return ActionType.REASON
