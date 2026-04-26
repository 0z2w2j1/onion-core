"""AgentRuntime, StateMachine, Planner, SlidingWindowMemory tests."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline
from onion_core.agent import (
    AgentLoop,
    AgentRuntime,
    AgentRuntimeError,
    DefaultPlanner,
    SlidingWindowMemory,
    StateMachine,
    StateTransitionError,
    ToolExecutor,
)
from onion_core.models import (
    ActionType,
    AgentConfig,
    AgentState,
    AgentStatus,
    FinishReason,
    ToolCall,
)
from onion_core.tools import ToolRegistry

# ═══════════════════════════════════════════════════════════════════════════════
# Exception classes
# ═══════════════════════════════════════════════════════════════════════════════

def test_execution_error_init():
    from onion_core.agent import ExecutionError
    cause = ValueError("inner")
    err = ExecutionError("msg", 3, cause)
    assert str(err) == "msg"
    assert err.retry_count == 3
    assert err.cause is cause


# ═══════════════════════════════════════════════════════════════════════════════
# StateMachine
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateMachine:
    def test_initial_status(self):
        state = AgentState()
        fsm = StateMachine(state)
        assert fsm.current_status == AgentStatus.IDLE

    def test_valid_transition(self):
        state = AgentState()
        fsm = StateMachine(state)
        fsm.transition_to(AgentStatus.THINKING)
        assert state.status == AgentStatus.THINKING

    def test_transition_to_same_status_is_noop(self):
        state = AgentState()
        fsm = StateMachine(state)
        result = fsm.transition_to(AgentStatus.IDLE)
        assert result.status == AgentStatus.IDLE

    def test_invalid_transition_raises(self):
        state = AgentState()
        fsm = StateMachine(state)
        with pytest.raises(StateTransitionError, match="Invalid transition"):
            fsm.transition_to(AgentStatus.FINISHED)

    def test_can_transition_to(self):
        state = AgentState()
        fsm = StateMachine(state)
        assert fsm.can_transition_to(AgentStatus.THINKING) is True
        assert fsm.can_transition_to(AgentStatus.FINISHED) is False

    def test_on_transition_callback(self):
        state = AgentState()
        fsm = StateMachine(state)
        events = []

        def listener(prev, target):
            events.append((prev, target))

        fsm.on_transition(listener)
        fsm.transition_to(AgentStatus.THINKING)
        assert len(events) == 1
        assert events[0] == (AgentStatus.IDLE, AgentStatus.THINKING)

    def test_on_transition_callback_error_suppressed(self):
        state = AgentState()
        fsm = StateMachine(state)

        def broken(prev, target):
            raise RuntimeError("oops")

        fsm.on_transition(broken)
        fsm.transition_to(AgentStatus.THINKING)
        assert state.status == AgentStatus.THINKING

    @pytest.mark.parametrize(
        ("status", "has_tool_calls", "llm_finished", "expected"),
        [
            (AgentStatus.ERROR, False, False, ActionType.ERROR),
            (AgentStatus.CANCELLED, False, False, ActionType.ERROR),
            (AgentStatus.THINKING, False, True, ActionType.FINISH),
            (AgentStatus.THINKING, True, False, ActionType.ACT),
            (AgentStatus.THINKING, False, False, ActionType.REASON),
        ],
    )
    def test_determine_next_action(self, status, has_tool_calls, llm_finished, expected):
        state = AgentState()
        state.set_status(status)
        fsm = StateMachine(state)
        result = fsm.determine_next_action(has_tool_calls, llm_finished)
        assert result == expected


# ═══════════════════════════════════════════════════════════════════════════════
# DefaultPlanner
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaultPlanner:
    @pytest.mark.asyncio
    async def test_planner_error_state(self):
        config = AgentConfig(max_steps=10)
        planner = DefaultPlanner(config)
        state = AgentState()
        state.set_status(AgentStatus.ERROR)
        decision = await planner.decide(state, None)
        assert decision.action_type == ActionType.ERROR

    @pytest.mark.asyncio
    async def test_planner_cancelled_state(self):
        config = AgentConfig(max_steps=10)
        planner = DefaultPlanner(config)
        state = AgentState()
        state.set_status(AgentStatus.CANCELLED)
        decision = await planner.decide(state, None)
        assert decision.action_type == ActionType.ERROR

    @pytest.mark.asyncio
    async def test_planner_max_steps(self):
        config = AgentConfig(max_steps=5)
        planner = DefaultPlanner(config)
        state = AgentState()
        state.steps = 5
        decision = await planner.decide(state, None)
        assert decision.action_type == ActionType.FINISH
        assert decision.metadata.get("max_steps_reached") is True

    @pytest.mark.asyncio
    async def test_planner_no_response(self):
        config = AgentConfig(max_steps=10)
        planner = DefaultPlanner(config)
        state = AgentState()
        decision = await planner.decide(state, None)
        assert decision.action_type == ActionType.REASON

    @pytest.mark.asyncio
    async def test_planner_has_tool_calls(self):
        config = AgentConfig(max_steps=10)
        planner = DefaultPlanner(config)
        state = AgentState()
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="t1", name="tool", arguments={})],
            finish_reason=FinishReason.TOOL_CALLS,
        )
        decision = await planner.decide(state, response)
        assert decision.action_type == ActionType.ACT
        assert decision.metadata.get("tool_count") == 1

    @pytest.mark.asyncio
    async def test_planner_finished(self):
        config = AgentConfig(max_steps=10)
        planner = DefaultPlanner(config)
        state = AgentState()
        response = LLMResponse(content="done", finish_reason=FinishReason.STOP)
        decision = await planner.decide(state, response)
        assert decision.action_type == ActionType.FINISH

    @pytest.mark.asyncio
    async def test_planner_continue_reasoning(self):
        config = AgentConfig(max_steps=10)
        planner = DefaultPlanner(config)
        state = AgentState()
        response = LLMResponse(content="thinking...", finish_reason=None)
        decision = await planner.decide(state, response)
        assert decision.action_type == ActionType.REASON


# ═══════════════════════════════════════════════════════════════════════════════
# SlidingWindowMemory & _TokenEstimator
# ═══════════════════════════════════════════════════════════════════════════════

class TestSlidingWindowMemory:
    def test_max_tokens_setter_validates(self):
        config = AgentConfig(memory_max_tokens=1024)
        mem = SlidingWindowMemory(config)
        with pytest.raises(ValueError, match="at least 256"):
            mem.max_tokens = 100
        mem.max_tokens = 512
        assert mem.max_tokens == 512

    def test_get_token_estimate(self):
        config = AgentConfig(memory_max_tokens=4000)
        mem = SlidingWindowMemory(config)
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
        estimate = mem.get_token_estimate(messages)
        assert estimate > 0

    def test_trim_empty_messages(self):
        config = AgentConfig(memory_max_tokens=1024)
        mem = SlidingWindowMemory(config)
        result = mem.trim([])
        assert result == []

    def test_trim_under_limit_returns_all(self):
        config = AgentConfig(memory_max_tokens=4000)
        mem = SlidingWindowMemory(config)
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
        ]
        result = mem.trim(messages)
        assert result == messages

    @pytest.mark.asyncio
    async def test_trim_with_summary_no_summarizer_falls_back(self):
        config = AgentConfig(memory_max_tokens=1024)
        mem = SlidingWindowMemory(config)
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="hello " * 1000),
            Message(role="assistant", content="world " * 1000),
            Message(role="user", content="bye " * 1000),
        ]
        result = await mem.trim_with_summary(messages)
        assert len(result) <= len(messages)

    @pytest.mark.asyncio
    async def test_trim_with_summary_under_limit_no_op(self):
        config = AgentConfig(memory_max_tokens=4000)
        mem = SlidingWindowMemory(config)

        class FakeSummarizer:
            async def summarize(self, msgs):
                return "summary text"

        mem._summarizer = FakeSummarizer()
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
        ]
        result = await mem.trim_with_summary(messages)
        assert result == messages

    @pytest.mark.asyncio
    async def test_trim_with_summary_summarizer_fails(self):
        config = AgentConfig(memory_max_tokens=1024)
        mem = SlidingWindowMemory(config)

        class FailingSummarizer:
            async def summarize(self, msgs):
                raise RuntimeError("summarizer failed")

        mem._summarizer = FailingSummarizer()
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="hello " * 500),
        ]
        result = await mem.trim_with_summary(messages)
        assert len(result) <= len(messages)

    def test_trim_system_exceeds_limit(self):
        config = AgentConfig(memory_max_tokens=256)
        mem = SlidingWindowMemory(config)
        messages = [
            Message(role="system", content="x" * 5000),
            Message(role="user", content="hello"),
        ]
        result = mem.trim(messages)
        assert len(result) > 0

    def test_token_estimator_tiktoken_path(self):
        config = AgentConfig(memory_max_tokens=4000)
        mem = SlidingWindowMemory(config)
        messages = [Message(role="user", content="hello world")]
        estimate = mem.get_token_estimate(messages)
        assert estimate >= 2

    def test_token_estimator_fallback(self):
        from onion_core.agent import _TokenEstimator
        est = _TokenEstimator(encoding_name="nonexistent_encoding")
        messages = [Message(role="user", content="hello world")]
        estimate = est.estimate_tokens(messages)
        assert estimate > 0


# ═══════════════════════════════════════════════════════════════════════════════
# AgentRuntime
# ═══════════════════════════════════════════════════════════════════════════════

class _MockProvider(EchoProvider):
    def __init__(self, responses: list[LLMResponse] | None = None):
        super().__init__(reply="done")
        self._responses = responses or [
            LLMResponse(content="done", finish_reason=FinishReason.STOP),
        ]
        self._idx = 0

    async def complete(self, context: AgentContext) -> LLMResponse:
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


class TestAgentRuntime:
    def test_init_validates_provider(self):
        registry = ToolRegistry()
        with pytest.raises(AgentRuntimeError, match="provider"):
            AgentRuntime(AgentConfig(), llm_provider=None, tool_registry=registry)  # type: ignore[arg-type]

    def test_init_validates_registry(self):
        provider = EchoProvider()
        with pytest.raises(AgentRuntimeError, match="registry"):
            AgentRuntime(AgentConfig(), llm_provider=provider, tool_registry=None)  # type: ignore[arg-type]

    def test_state_property_before_run_raises(self):
        provider = EchoProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(), llm_provider=provider, tool_registry=registry)
        with pytest.raises(AgentRuntimeError, match="not initialized"):
            _ = runtime.state

    def test_fsm_property_before_run_raises(self):
        provider = EchoProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(), llm_provider=provider, tool_registry=registry)
        with pytest.raises(AgentRuntimeError, match="not initialized"):
            _ = runtime.fsm

    @pytest.mark.asyncio
    async def test_run_finishes_immediately_no_tools(self):
        provider = _MockProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(max_steps=5), llm_provider=provider, tool_registry=registry)
        state = await runtime.run("Hello")
        assert state.status == AgentStatus.FINISHED
        assert state.steps >= 1

    @pytest.mark.asyncio
    async def test_run_with_tool_call(self):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="t1", name="ping", arguments={})],
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(content="done", finish_reason=FinishReason.STOP),
        ]
        provider = _MockProvider(responses)
        registry = ToolRegistry()

        @registry.register
        async def ping() -> str:
            return "pong"

        runtime = AgentRuntime(AgentConfig(max_steps=5), llm_provider=provider, tool_registry=registry)
        state = await runtime.run("test")
        assert state.status == AgentStatus.FINISHED

    @pytest.mark.asyncio
    async def test_run_respects_max_steps(self):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="t1", name="ping", arguments={})],
                finish_reason=FinishReason.TOOL_CALLS,
            ),
        ] * 10
        provider = _MockProvider(responses)
        registry = ToolRegistry()

        @registry.register
        async def ping() -> str:
            return "pong"

        runtime = AgentRuntime(AgentConfig(max_steps=3), llm_provider=provider, tool_registry=registry)
        state = await runtime.run("test")
        assert state.steps <= 3

    @pytest.mark.asyncio
    async def test_run_with_system_prompt(self):
        provider = _MockProvider()
        registry = ToolRegistry()
        config = AgentConfig(max_steps=3, system_prompt="You are a bot.")
        runtime = AgentRuntime(config, llm_provider=provider, tool_registry=registry)
        state = await runtime.run("Hello")
        sys_msgs = [m for m in state.messages if m.role == "system"]
        assert any("You are a bot." in str(m.content) for m in sys_msgs)

    def test_cancel_sets_flag(self):
        provider = EchoProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(max_steps=10), llm_provider=provider, tool_registry=registry)
        assert runtime._cancelled is False
        runtime.cancel()
        assert runtime._cancelled is True

    @pytest.mark.asyncio
    async def test_step_hooks(self):
        provider = _MockProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(max_steps=3), llm_provider=provider, tool_registry=registry)
        events = []

        def hook(record):
            events.append(record.step_index)

        runtime.on_step(hook)
        await runtime.run("test")
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_error_hooks(self):
        class FailingProvider(EchoProvider):
            async def complete(self, context):
                raise RuntimeError("LLM failed")

        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(max_steps=3), llm_provider=FailingProvider(), tool_registry=registry)
        errors = []

        def hook(run_id, exc):
            errors.append((run_id, str(exc)))

        runtime.on_error(hook)
        state = await runtime.run("test")
        assert state.status == AgentStatus.ERROR
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_run_streaming_yields_steps(self):
        provider = _MockProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(max_steps=3), llm_provider=provider, tool_registry=registry)
        steps = []
        async for step in runtime.run_streaming("test"):
            steps.append(step)
        assert len(steps) > 0

    @pytest.mark.asyncio
    async def test_on_step_hook_error_suppressed(self):
        provider = _MockProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(AgentConfig(max_steps=3), llm_provider=provider, tool_registry=registry)

        def broken(record):
            raise RuntimeError("hook error")

        runtime.on_step(broken)
        state = await runtime.run("test")
        assert state.status == AgentStatus.FINISHED


# ═══════════════════════════════════════════════════════════════════════════════
# ToolExecutor
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolExecutor:
    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        executor = ToolExecutor(registry, AgentConfig(tool_max_retries=0))
        result = await executor.execute(ToolCall(id="t1", name="missing", arguments={}))
        assert result.is_error
        assert "not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_all_empty(self):
        registry = ToolRegistry()
        executor = ToolExecutor(registry, AgentConfig(tool_max_retries=0))
        results = await executor.execute_all([])
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_sync_function(self):
        registry = ToolRegistry()

        @registry.register
        def add(a: int, b: int) -> int:
            return a + b

        executor = ToolExecutor(registry, AgentConfig(tool_max_retries=0, tool_timeout_seconds=5.0))
        result = await executor.execute(ToolCall(id="t1", name="add", arguments={"a": 1, "b": 2}))
        assert result.result == "3"

    @pytest.mark.asyncio
    async def test_execute_retry_then_success(self):
        registry = ToolRegistry()
        call_count = {"count": 0}

        @registry.register
        async def flaky() -> str:
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise RuntimeError("transient")
            return "ok"

        executor = ToolExecutor(registry, AgentConfig(tool_max_retries=3, tool_timeout_seconds=5.0))
        result = await executor.execute(ToolCall(id="t1", name="flaky", arguments={}))
        assert result.result == "ok"
        assert result.retry_count == 2

    @pytest.mark.asyncio
    async def test_execute_all_concurrent(self):
        registry = ToolRegistry()

        @registry.register
        async def tool_a() -> str:
            return "A"

        @registry.register
        async def tool_b() -> str:
            return "B"

        executor = ToolExecutor(registry, AgentConfig(tool_max_retries=0, tool_timeout_seconds=5.0, max_concurrent_tools=5))
        results = await executor.execute_all([
            ToolCall(id="t1", name="tool_a", arguments={}),
            ToolCall(id="t2", name="tool_b", arguments={}),
        ])
        assert len(results) == 2
        assert results[0].result in ("A", "B")
        assert results[1].result in ("A", "B")


# ═══════════════════════════════════════════════════════════════════════════════
# AgentLoop edge cases (supplementing test_agent.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentLoopSupplemental:
    @pytest.mark.asyncio
    async def test_agent_loop_dedup_policy_off(self):
        registry = ToolRegistry()
        exec_count = {"count": 0}

        @registry.register
        async def ping() -> str:
            exec_count["count"] += 1
            return "pong"

        class DedupProvider(EchoProvider):
            def __init__(self):
                super().__init__(reply="done")
                self.call_num = 0

            async def complete(self, context):
                self.call_num += 1
                if self.call_num == 1:
                    return LLMResponse(
                        content=None,
                        tool_calls=[
                            ToolCall(id="same", name="ping", arguments={}),
                            ToolCall(id="same", name="ping", arguments={}),
                        ],
                        finish_reason=FinishReason.TOOL_CALLS,
                    )
                return LLMResponse(content="done", finish_reason=FinishReason.STOP)

        provider = DedupProvider()
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)
        ctx = AgentContext(
            messages=[Message(role="user", content="hi")],
            config={"tool_call_dedup_policy": "off"},
        )
        resp = await loop.run(ctx)
        assert resp.finish_reason == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_agent_loop_dept_with_signature_dedup(self):
        registry = ToolRegistry()
        exec_count = {"count": 0}

        @registry.register
        async def ping(city: str) -> str:
            exec_count["count"] += 1
            return f"pong:{city}"

        class SigProvider(EchoProvider):
            def __init__(self):
                super().__init__(reply="done")
                self.call_num = 0

            async def complete(self, context):
                self.call_num += 1
                if self.call_num == 1:
                    return LLMResponse(
                        content=None,
                        tool_calls=[
                            ToolCall(id="a1", name="ping", arguments={"city": "bj"}),
                            ToolCall(id="a2", name="ping", arguments={"city": "bj"}),
                        ],
                        finish_reason=FinishReason.TOOL_CALLS,
                    )
                return LLMResponse(content="done", finish_reason=FinishReason.STOP)

        provider = SigProvider()
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)
        ctx = AgentContext(
            messages=[Message(role="user", content="hi")],
            config={"tool_call_dedup_policy": "strict"},
        )
        await loop.run(ctx)
        assert exec_count["count"] == 1

    @pytest.mark.asyncio
    async def test_agent_loop_progress_detection_stops(self):
        registry = ToolRegistry()

        @registry.register
        async def ping() -> str:
            return "pong"

        class StuckProvider(EchoProvider):
            def __init__(self):
                super().__init__(reply="done")
                self.call_num = 0

            async def complete(self, context):
                self.call_num += 1
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(id="t1", name="ping", arguments={})],
                    finish_reason=FinishReason.TOOL_CALLS,
                )

        provider = StuckProvider()
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry, max_turns=10)
        ctx = AgentContext(
            messages=[Message(role="user", content="hi")],
            config={"agent_progress_window": 2},
        )
        resp = await loop.run(ctx)
        assert resp is not None
