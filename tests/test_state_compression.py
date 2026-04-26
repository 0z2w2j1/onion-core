"""Stress test for AgentState compression across multi-round sessions."""

from __future__ import annotations

from src.core.state import AgentState
from src.schema.models import (
    ActionType,
    AgentConfig,
    AgentStatus,
    Message,
    MessageRole,
    StepRecord,
    UsageStats,
)


def _make_message(role: MessageRole, index: int) -> Message:
    return Message(role=role, content=f"Message content number {index} " + "padding " * 20)


def _make_step(index: int) -> StepRecord:
    return StepRecord(
        step_index=index,
        trace_id=f"trace.{index}",
        action_type=ActionType.REASON,
        status=AgentStatus.THINKING,
        duration_ms=100.0,
        token_usage=UsageStats(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )


class TestStateCompression:
    def test_compress_trims_excess_messages(self):
        cfg = AgentConfig(state_max_messages=10, state_max_history_steps=50)
        state = AgentState()
        state.add_message(Message(role=MessageRole.SYSTEM, content="System prompt"))
        for i in range(50):
            state.add_message(_make_message(MessageRole.USER, i))
            state.add_message(_make_message(MessageRole.ASSISTANT, i))

        assert len(state.messages) == 101
        removed = state.compress(cfg)
        assert removed > 0
        assert len(state.messages) <= 10
        assert state.messages[0].role == MessageRole.SYSTEM

    def test_archive_history_trims_excess_steps(self):
        cfg = AgentConfig(state_max_messages=200, state_max_history_steps=5)
        state = AgentState()
        for i in range(50):
            state.record_step(_make_step(i))

        assert len(state.steps_history) == 50
        archived = state.archive_history(cfg)
        assert archived == 45
        assert len(state.steps_history) == 5
        assert len(state.archived_summaries) == 45
        assert "step 0" in state.archived_summaries[0]

    def test_compact_runs_both(self):
        cfg = AgentConfig(state_max_messages=20, state_max_history_steps=5)
        state = AgentState()
        for i in range(100):
            state.add_message(_make_message(MessageRole.USER, i))
        for i in range(50):
            state.record_step(_make_step(i))

        result = state.compact(cfg)
        assert result["messages_removed"] > 0
        assert result["history_archived"] > 0
        assert len(state.messages) <= 20
        assert len(state.steps_history) <= 5

    def test_compress_noop_when_under_limit(self):
        cfg = AgentConfig(state_max_messages=200, state_max_history_steps=100)
        state = AgentState()
        for i in range(5):
            state.add_message(_make_message(MessageRole.USER, i))

        removed = state.compress(cfg)
        assert removed == 0
        assert len(state.messages) == 5

    def test_archive_history_noop_when_under_limit(self):
        cfg = AgentConfig(state_max_messages=200, state_max_history_steps=100)
        state = AgentState()
        for i in range(5):
            state.record_step(_make_step(i))

        archived = state.archive_history(cfg)
        assert archived == 0

    def test_compress_preserves_system_messages(self):
        cfg = AgentConfig(state_max_messages=10)
        state = AgentState()
        state.add_message(Message(role=MessageRole.SYSTEM, content="System"))
        state.add_message(Message(role=MessageRole.SYSTEM, content="System 2"))
        for i in range(100):
            state.add_message(_make_message(MessageRole.USER, i))

        state.compress(cfg)
        assert state.messages[0].role == MessageRole.SYSTEM
        assert state.messages[1].role == MessageRole.SYSTEM

    def test_diagnose_returns_counts(self):
        state = AgentState()
        for i in range(10):
            state.add_message(_make_message(MessageRole.USER, i))
        for i in range(3):
            state.record_step(_make_step(i))
        state.archived_summaries.append("archived step 1")

        info = state.diagnose()
        assert info["message_count"] == 10
        assert info["history_count"] == 3
        assert info["archive_count"] == 1
        assert info["total_chars"] > 0


class TestMultiRoundStress:
    def test_1000_turn_session_no_oom(self):
        cfg = AgentConfig(
            state_max_messages=50,
            state_max_history_steps=20,
            max_concurrent_tools=5,
        )
        state = AgentState()

        for turn in range(1000):
            state.add_message(
                Message(role=MessageRole.USER, content=f"Turn {turn} input " + "x" * 100)
            )
            state.add_message(
                Message(role=MessageRole.ASSISTANT, content=f"Turn {turn} output " + "y" * 100)
            )
            state.record_step(
                StepRecord(
                    step_index=turn,
                    trace_id=f"trace.{turn}",
                    action_type=ActionType.REASON,
                    status=AgentStatus.THINKING,
                    duration_ms=50.0,
                    token_usage=UsageStats(prompt_tokens=200, completion_tokens=80, total_tokens=280),
                )
            )
            state.compact(cfg)

        assert len(state.messages) <= 50
        assert len(state.steps_history) <= 20
        assert len(state.archived_summaries) > 900
        assert state.diagnose()["message_count"] <= 50

    def test_state_memory_upper_bound_never_exceeded(self):
        cfg = AgentConfig(state_max_messages=30, state_max_history_steps=10)
        state = AgentState()

        for i in range(500):
            state.add_message(
                Message(role=MessageRole.USER, content=f"Message {i} " + "data " * 50)
            )
            state.record_step(_make_step(i))
            state.compact(cfg)

        assert len(state.messages) <= 30
        assert len(state.steps_history) <= 10

    def test_clone_and_resume(self):
        cfg = AgentConfig(state_max_messages=20, state_max_history_steps=10)
        state = AgentState()
        for i in range(100):
            state.add_message(_make_message(MessageRole.USER, i))
        state.compact(cfg)

        cloned = state.clone()
        assert cloned.run_id == state.run_id
        assert len(cloned.messages) == len(state.messages)
        cloned.add_message(Message(role=MessageRole.USER, content="resumed"))
        assert len(cloned.messages) == len(state.messages) + 1
