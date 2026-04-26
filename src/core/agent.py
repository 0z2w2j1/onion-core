from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable

from src.core.executor import ToolExecutor
from src.core.planner import BasePlanner, DefaultPlanner, PlannerDecision
from src.core.state import AgentState, StateMachine
from src.llm.base import BaseLLMClient, LLMError
from src.memory.buffer import SlidingWindowMemory
from src.observability.context import RequestContext
from src.schema.models import (
    ActionType,
    AgentConfig,
    AgentStatus,
    Message,
    MessageRole,
    StepRecord,
    UsageStats,
)
from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentRuntimeError(Exception):
    pass


class AgentRuntime:
    def __init__(
        self,
        config: AgentConfig,
        llm_client: BaseLLMClient,
        tool_registry: ToolRegistry,
        planner: BasePlanner | None = None,
        memory: SlidingWindowMemory | None = None,
        owns_client: bool = True,
    ) -> None:
        if not llm_client:
            raise AgentRuntimeError("llm_client is required")
        if not tool_registry:
            raise AgentRuntimeError("tool_registry is required")

        self._config = config
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._planner = planner or DefaultPlanner(config)
        self._memory = memory or SlidingWindowMemory(config)
        self._executor = ToolExecutor(tool_registry, config)
        self._state: AgentState | None = None
        self._fsm: StateMachine | None = None
        self._cancelled = False
        self._owns_client = owns_client
        self._step_hooks: list[Callable[[StepRecord], None]] = []
        self._error_hooks: list[Callable[[str, Exception], None]] = []

    @property
    def state(self) -> AgentState:
        if self._state is None:
            raise AgentRuntimeError("Agent not initialized. Call run() first.")
        return self._state

    @property
    def fsm(self) -> StateMachine:
        if self._fsm is None:
            raise AgentRuntimeError("Agent not initialized. Call run() first.")
        return self._fsm

    def on_step(self, callback: Callable[[StepRecord], None]) -> None:
        self._step_hooks.append(callback)

    def on_error(self, callback: Callable[[str, Exception], None]) -> None:
        self._error_hooks.append(callback)

    def cancel(self) -> None:
        self._cancelled = True
        if self._state:
            with contextlib.suppress(Exception):
                self._state.set_status(AgentStatus.CANCELLED)

    async def run(self, user_message: str, state: AgentState | None = None) -> AgentState:
        self._cancelled = False

        if state is not None:
            self._state = state
        else:
            self._state = AgentState()

        self._fsm = StateMachine(self._state)
        assert self._state is not None
        assert self._fsm is not None

        if self._config.system_prompt:
            self._state.add_message(
                Message(role=MessageRole.SYSTEM, content=self._config.system_prompt)
            )

        self._state.add_message(Message(role=MessageRole.USER, content=user_message))

        with RequestContext(
            request_id=self._state.run_id,
            trace_id=self._state.session_id,
        ):
            logger.info(
                "AgentRuntime starting: run_id=%s session_id=%s max_steps=%d",
                self._state.run_id,
                self._state.session_id,
                self._config.max_steps,
            )

            try:
                self._fsm.transition_to(AgentStatus.THINKING)

                while self._state.steps < self._config.max_steps and not self._cancelled:
                    self._state.increment_step()
                    step_index = self._state.steps
                    trace_id_str = f"{self._state.run_id}.{step_index}"

                    self._state.compact(self._config)

                    logger.info(
                        "Step %d starting: trace_id=%s status=%s",
                        step_index,
                        trace_id_str,
                        self._state.status.value,
                    )

                    try:
                        decision = await self._run_think_phase(trace_id_str, step_index)
                    except LLMError as e:
                        logger.error("LLM error at step %d: %s", step_index, e, exc_info=True)
                        self._handle_error(trace_id_str, str(e), e)
                        self._fsm.transition_to(AgentStatus.ERROR)
                        break

                    if decision is None:
                        logger.warning("Step %d produced no decision, breaking", step_index)
                        self._fsm.transition_to(AgentStatus.FINISHED)
                        break

                    if decision.action_type == ActionType.FINISH:
                        self._fsm.transition_to(AgentStatus.FINISHED)
                        logger.info("Agent finished at step %d: %s", step_index, decision.reasoning)
                        break

                    if decision.action_type == ActionType.ACT:
                        await self._run_act_phase(trace_id_str, step_index)
                    elif decision.action_type == ActionType.ERROR:
                        self._fsm.transition_to(AgentStatus.ERROR)
                        break

                if self._cancelled:
                    self._state.set_status(AgentStatus.CANCELLED)
                    logger.info("Agent cancelled at step %d", self._state.steps)

                if self._state.steps >= self._config.max_steps and self._state.status == AgentStatus.THINKING:
                    self._state.set_status(AgentStatus.FINISHED)
                    logger.warning(
                        "Agent reached max_steps (%d), forced finish",
                        self._config.max_steps,
                    )

            except Exception as e:
                logger.exception("AgentRuntime fatal error: %s", e)
                assert self._state is not None
                self._state.set_status(AgentStatus.ERROR)
                last_step = self._state.last_step
                if last_step:
                    last_step.error = str(e)
                for hook in self._error_hooks:
                    with contextlib.suppress(Exception):
                        hook(self._state.run_id, e)

            finally:
                if self._owns_client:
                    await self._llm_client.close()

            return self._state

    async def _run_think_phase(self, trace_id: str, step_index: int) -> PlannerDecision | None:
        assert self._state is not None
        assert self._fsm is not None
        start = time.monotonic()
        self._fsm.transition_to(AgentStatus.THINKING)

        trimmed = self._memory.trim(self._state.messages)

        llm_response = await self._llm_client.complete(trimmed)

        assistant_msg = llm_response.to_assistant_message()
        self._state.add_message(assistant_msg)

        decision = await self._planner.decide(self._state, llm_response)

        usage = llm_response.usage or UsageStats()
        step_record = StepRecord(
            step_index=step_index,
            trace_id=trace_id,
            action_type=decision.action_type,
            status=self._state.status,
            llm_response=llm_response,
            duration_ms=(time.monotonic() - start) * 1000,
            token_usage=usage,
            metadata=decision.metadata,
        )
        self._state.record_step(step_record)
        self._emit_step(step_record)

        logger.info(
            "Step %d think: trace_id=%s action=%s tokens=%d latency=%.0fms",
            step_index,
            trace_id,
            decision.action_type.value,
            usage.total_tokens,
            step_record.duration_ms,
        )

        return decision

    async def _run_act_phase(self, trace_id: str, step_index: int) -> None:
        assert self._state is not None
        assert self._fsm is not None
        self._fsm.transition_to(AgentStatus.ACTING)
        last_step = self._state.last_step
        if last_step is None or last_step.llm_response is None:
            return

        tool_calls = last_step.llm_response.tool_calls
        if not tool_calls:
            return

        start = time.monotonic()
        logger.info(
            "Step %d acting: trace_id=%s tool_count=%d",
            step_index,
            trace_id,
            len(tool_calls),
        )

        results = await self._executor.execute_all(tool_calls)

        for r in results:
            self._state.add_message(r.to_message())

        if last_step:
            last_step.tool_results = results
            last_step.duration_ms += (time.monotonic() - start) * 1000

        logger.info(
            "Step %d act complete: trace_id=%s success=%d/%d",
            step_index,
            trace_id,
            sum(1 for r in results if not r.is_error),
            len(results),
        )

        self._fsm.transition_to(AgentStatus.THINKING)

    def _emit_step(self, step: StepRecord) -> None:
        for hook in self._step_hooks:
            with contextlib.suppress(Exception):
                hook(step)

    def _handle_error(self, trace_id: str, message: str, exc: Exception) -> None:
        for hook in self._error_hooks:
            with contextlib.suppress(Exception):
                hook(message, exc)

    async def run_streaming(
        self, user_message: str, state: AgentState | None = None
    ) -> AgentState:
        raise NotImplementedError("Streaming mode will be implemented in v2")
