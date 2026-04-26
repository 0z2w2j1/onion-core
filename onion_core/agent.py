"""
Onion Core - Agent Runtime & Agent Loop

提供两种 Agent 执行模式：
  - AgentRuntime: 完整的 ReAct 循环（think → act → think → act → finish）
  - AgentLoop: 简化的工具调用循环（基于 Pipeline 中间件链）

AgentRuntime 适用于需要完整状态机、自定义规划器和记忆管理的场景。
AgentLoop 适用于需要 Pipeline 中间件链（安全、限流、可观测性）的场景。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import signal
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import tiktoken

from .models import (
    ActionType,
    AgentConfig,
    AgentContext,
    AgentState,
    AgentStatus,
    LLMResponse,
    Message,
    MessageRole,
    RetryOutcome,
    RetryPolicy,
    StepRecord,
    StreamChunk,
    ToolCall,
    ToolResult,
    UsageStats,
    lookup_model_limits,
)
from .pipeline import Pipeline
from .provider import LLMProvider
from .tools import ToolRegistry

_DEFAULT_RETRY_POLICY = RetryPolicy()

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 异常
# ═══════════════════════════════════════════════════════════════════════════════

class AgentLoopError(Exception):
    pass


class AgentRuntimeError(Exception):
    pass


class StateTransitionError(Exception):
    pass


class ExecutionError(Exception):
    def __init__(self, message: str, retry_count: int, cause: Exception) -> None:
        super().__init__(message)
        self.retry_count = retry_count
        self.cause = cause


# ═══════════════════════════════════════════════════════════════════════════════
# AgentLoop — Pipeline 之上的工具调用循环
# ═══════════════════════════════════════════════════════════════════════════════

class AgentLoop:
    def __init__(
        self,
        pipeline: Pipeline,
        registry: ToolRegistry | None = None,
        max_turns: int = 10,
        raise_on_max_turns: bool = False,
        memory: SlidingWindowMemory | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._registry = registry or ToolRegistry()
        self._max_turns = max_turns
        self._raise_on_max_turns = raise_on_max_turns
        self._memory = memory

    async def run(self, context: AgentContext) -> LLMResponse:
        """
        执行 Agent 循环。
        
        注意：当使用 SlidingWindowMemory 时，每轮循环都会重新裁剪 messages，
        因此需要确保在裁剪后继续追加新的消息到 context.messages。
        """
        last_response: LLMResponse | None = None
        dedup_policy = self._get_tool_call_dedup_policy(context)
        progress_window = self._get_progress_window(context)
        recent_state_hashes: deque[str] = deque(maxlen=progress_window)

        for turn in range(self._max_turns):
            # 1. 内存裁剪（可能修改 context.messages）
            if self._memory is not None:
                trimmed_messages = self._memory.trim(context.messages)
                # 【关键】如果 trim 返回了新列表，更新 context.messages
                if trimmed_messages is not context.messages:
                    logger.info(
                        "[%s] Turn %d: Memory trimmed messages from %d to %d",
                        context.request_id, turn + 1, len(context.messages), len(trimmed_messages),
                    )
                    context.messages = trimmed_messages

            # 2. Pipeline 执行（中间件可能再次修改 context.messages）
            response = await self._pipeline.run(context)
            last_response = response

            if not response.has_tool_calls:
                logger.info("AgentLoop finished in %d turn(s).", turn + 1)
                return response

            logger.info("Turn %d: %d tool call(s).", turn + 1, len(response.tool_calls))

            turn_seen_ids: set[str] = set()
            turn_seen_signatures: set[str] = set()
            turn_result_summaries: list[str] = []

            # 3. 执行工具调用并追加结果到 context.messages
            for tool_call in response.tool_calls:
                call_signature = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True)}"
                if self._is_duplicate_tool_call(
                    tool_call, call_signature, dedup_policy,
                    turn_seen_ids, turn_seen_signatures,
                ):
                    logger.warning(
                        "[%s] Duplicate tool call skipped by policy=%s: id=%s, signature=%s",
                        context.request_id, dedup_policy, tool_call.id, call_signature,
                    )
                    continue

                intercepted = await self._pipeline.execute_tool_call(context, tool_call)
                tool_result = await self._registry.execute(intercepted, context)
                processed = await self._pipeline.execute_tool_result(context, tool_result)
                turn_result_summaries.append(self._summarize_tool_result(processed))

                result_text = (
                    str(processed.result) if not processed.is_error
                    else f"Error: {processed.error}"
                )
                context.messages.append(Message(
                    role=MessageRole.TOOL,
                    content=result_text,
                    name=processed.name,
                ))

            # 4. 追加助手回复到 context.messages
            context.messages.append(response.to_assistant_message())

            # 5. 检查状态进展
            turn_state_hash = self._build_turn_state_hash(response, turn_result_summaries)
            recent_state_hashes.append(turn_state_hash)
            if (
                progress_window > 0
                and len(recent_state_hashes) == progress_window
                and len(set(recent_state_hashes)) == 1
            ):
                logger.warning(
                    "[%s] No state progress detected for %d turns; stopping.",
                    context.request_id, progress_window,
                )
                return last_response

        logger.warning("AgentLoop reached max_turns=%d without stop.", self._max_turns)
        if self._raise_on_max_turns:
            raise AgentLoopError(
                f"Agent loop exceeded max_turns={self._max_turns} without a final response."
            )
        assert last_response is not None
        return last_response

    @staticmethod
    def _get_tool_call_dedup_policy(context: AgentContext) -> str:
        pipeline_cfg = context.config.get("onion", {}).get("pipeline", {})
        policy = context.config.get("tool_call_dedup_policy", pipeline_cfg.get("tool_call_dedup_policy", "relaxed"))
        return policy if policy in {"strict", "relaxed", "off"} else "relaxed"

    @staticmethod
    def _get_progress_window(context: AgentContext) -> int:
        pipeline_cfg = context.config.get("onion", {}).get("pipeline", {})
        window = context.config.get("agent_progress_window", pipeline_cfg.get("agent_progress_window", 3))
        try:
            return max(int(window), 0)
        except (TypeError, ValueError):
            return 3

    @staticmethod
    def _is_duplicate_tool_call(
        tool_call: ToolCall, call_signature: str, policy: str,
        turn_seen_ids: set[str], turn_seen_signatures: set[str],
    ) -> bool:
        if policy == "off":
            return False
        duplicate = tool_call.id in turn_seen_ids
        if policy == "strict":
            duplicate = duplicate or call_signature in turn_seen_signatures
        turn_seen_ids.add(tool_call.id)
        turn_seen_signatures.add(call_signature)
        return duplicate

    @staticmethod
    def _summarize_tool_result(result: ToolResult) -> str:
        payload = {"id": result.tool_call_id, "name": result.name, "error": result.error, "result": result.result}
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_turn_state_hash(response: LLMResponse, tool_result_summaries: list[str]) -> str:
        payload = {
            "finish_reason": response.finish_reason,
            "content": response.content,
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls],
            "tool_results": tool_result_summaries,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# 状态机 — AgentRuntime 内部状态转换
# ═══════════════════════════════════════════════════════════════════════════════

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
            try:
                listener(previous, target)
            except Exception as exc:
                logger.warning("StateMachine listener failed: %s", exc)
        return self._state

    def can_transition_to(self, target: AgentStatus) -> bool:
        return target in self.ALLOWED_TRANSITIONS.get(self._state.status, set())

    def on_transition(self, callback: Callable[[AgentStatus, AgentStatus], None]) -> None:
        self._listeners.append(callback)

    def determine_next_action(self, has_tool_calls: bool, llm_finished: bool) -> ActionType:
        if self._state.status in (AgentStatus.ERROR, AgentStatus.CANCELLED):
            return ActionType.ERROR
        if llm_finished and not has_tool_calls:
            return ActionType.FINISH
        if has_tool_calls:
            return ActionType.ACT
        return ActionType.REASON


# ═══════════════════════════════════════════════════════════════════════════════
# Planner — 决定 Agent 的下一步行动
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PlannerDecision:
    action_type: ActionType
    reasoning: str
    metadata: dict[str, object] = field(default_factory=dict)


class BasePlanner(ABC):
    @abstractmethod
    async def decide(self, state: AgentState, llm_response: LLMResponse | None) -> PlannerDecision:
        ...


class DefaultPlanner(BasePlanner):
    def __init__(self, config: AgentConfig) -> None:
        self._config = config

    async def decide(self, state: AgentState, llm_response: LLMResponse | None) -> PlannerDecision:
        if state.status in (AgentStatus.ERROR, AgentStatus.CANCELLED):
            return PlannerDecision(
                action_type=ActionType.ERROR,
                reasoning="Agent is in terminal error/cancelled state",
                metadata={"status": state.status.value},
            )

        if state.steps >= self._config.max_steps:
            return PlannerDecision(
                action_type=ActionType.FINISH,
                reasoning=f"Reached max_steps limit ({self._config.max_steps})",
                metadata={"max_steps_reached": True},
            )

        if llm_response is None:
            return PlannerDecision(
                action_type=ActionType.REASON,
                reasoning="No LLM response yet, need to reason first",
                metadata={},
            )

        if llm_response.has_tool_calls:
            return PlannerDecision(
                action_type=ActionType.ACT,
                reasoning=f"LLM requested {len(llm_response.tool_calls)} tool call(s)",
                metadata={"tool_count": len(llm_response.tool_calls)},
            )

        if llm_response.is_finished:
            reason_val = llm_response.finish_reason.value if llm_response.finish_reason else "unknown"
            return PlannerDecision(
                action_type=ActionType.FINISH,
                reasoning=f"LLM finished with reason: {reason_val}",
                metadata={"finish_reason": reason_val},
            )

        return PlannerDecision(
            action_type=ActionType.REASON,
            reasoning="Continue reasoning loop",
            metadata={},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ToolExecutor — 工具调用执行器（带重试、超时、并发控制）
# ═══════════════════════════════════════════════════════════════════════════════

class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        config: AgentConfig,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._retry_policy = retry_policy or _DEFAULT_RETRY_POLICY
        self._semaphore = asyncio.Semaphore(config.max_concurrent_tools)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        start = time.monotonic()
        tool_def = self._registry.get(tool_call.name)
        if tool_def is None:
            return ToolResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                error=f"Tool '{tool_call.name}' not found in registry",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        for attempt in range(self._config.tool_max_retries + 1):
            try:
                kwargs = dict(tool_call.arguments)
                if asyncio.iscoroutinefunction(tool_def.func):
                    result = await asyncio.wait_for(
                        tool_def.func(**kwargs),
                        timeout=self._config.tool_timeout_seconds,
                    )
                else:
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda kw=kwargs: tool_def.func(**kw)),  # type: ignore[misc]
                        timeout=self._config.tool_timeout_seconds,
                    )

                if not isinstance(result, (str, dict, list)):
                    result = str(result)
                return ToolResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    result=result,
                    duration_ms=(time.monotonic() - start) * 1000,
                    retry_count=attempt,
                )
            except TimeoutError:
                if attempt < self._config.tool_max_retries:
                    logger.warning("Tool '%s' attempt %d timed out, retrying...", tool_call.name, attempt + 1)
                    await asyncio.sleep(2 ** attempt)
                    continue
                return ToolResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    error=f"Tool '{tool_call.name}' timed out after {self._config.tool_timeout_seconds}s",
                    duration_ms=(time.monotonic() - start) * 1000,
                    retry_count=attempt,
                )
            except Exception as e:
                outcome = self._retry_policy.classify(e)
                if outcome == RetryOutcome.FATAL:
                    return ToolResult(
                        tool_call_id=tool_call.id, name=tool_call.name,
                        error=f"{type(e).__name__}: {e}",
                        duration_ms=(time.monotonic() - start) * 1000,
                        retry_count=attempt,
                    )
                if attempt < self._config.tool_max_retries:
                    logger.warning("Tool '%s' attempt %d failed: %s, retrying...", tool_call.name, attempt + 1, e)
                    await asyncio.sleep(2 ** attempt)
                    continue
                return ToolResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    error=f"{type(e).__name__}: {e}",
                    duration_ms=(time.monotonic() - start) * 1000,
                    retry_count=attempt,
                )

        return ToolResult(
            tool_call_id=tool_call.id, name=tool_call.name,
            error="Tool execution ended unexpectedly",
            duration_ms=(time.monotonic() - start) * 1000,
            retry_count=0,
        )

    async def execute_all(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        if not tool_calls:
            return []

        async def _execute_one(tc: ToolCall) -> ToolResult:
            async with self._semaphore:
                return await self.execute(tc)

        tasks = [_execute_one(tc) for tc in tool_calls]
        return await asyncio.gather(*tasks)


# ═══════════════════════════════════════════════════════════════════════════════
# SlidingWindowMemory — 滑动窗口记忆管理
# ═══════════════════════════════════════════════════════════════════════════════

class MemorySummarizer(ABC):
    @abstractmethod
    async def summarize(self, messages: list[Message]) -> str:
        ...


class _TokenEstimator:
    AVERAGE_CHARS_PER_TOKEN = 4.0

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding = None
        with contextlib.suppress(Exception):
            self._encoding = tiktoken.get_encoding(encoding_name)

    def estimate_tokens(self, messages: list[Message]) -> int:
        if self._encoding is not None:
            return self._estimate_tiktoken(messages)
        return self._estimate_fallback(messages)

    def _estimate_tiktoken(self, messages: list[Message]) -> int:
        total = 0
        enc = self._encoding
        assert enc is not None
        for m in messages:
            total += 4
            if m.name:
                total += 1
            content = m.content if isinstance(m.content, str) else ""
            total += len(enc.encode(content))
        return max(1, total)

    def _estimate_fallback(self, messages: list[Message]) -> int:
        total = 0.0
        for m in messages:
            total += 4
            if m.name:
                total += 1
            content = m.content if isinstance(m.content, str) else ""
            total += len(content) / self.AVERAGE_CHARS_PER_TOKEN
        return max(1, int(total))


class SlidingWindowMemory:
    def __init__(
        self,
        config: AgentConfig,
        summarizer: MemorySummarizer | None = None,
    ) -> None:
        self._max_tokens = config.memory_max_tokens
        self._summarizer = summarizer
        self._token_counter = _TokenEstimator()

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        if value < 256:
            raise ValueError("max_tokens must be at least 256")
        self._max_tokens = value

    def trim(self, messages: list[Message]) -> list[Message]:
        if not messages:
            return []

        total = self._token_counter.estimate_tokens(messages)
        if total <= self._max_tokens:
            return messages

        logger.info("Trimming messages: %d tokens exceeds limit of %d", total, self._max_tokens)

        system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
        non_system = [m for m in messages if m.role != MessageRole.SYSTEM]
        system_reserve = self._token_counter.estimate_tokens(system_messages)
        available = self._max_tokens - system_reserve

        if available <= 0:
            logger.error("System messages alone (%d tokens) exceed memory limit (%d tokens)", system_reserve, self._max_tokens)
            return system_messages[:-max(1, len(system_messages) - 1)] + (non_system[-1:] if non_system else [])

        kept = []
        running = 0
        for m in reversed(non_system):
            t = self._token_counter.estimate_tokens([m])
            if running + t > available:
                break
            kept.append(m)
            running += t
        kept.reverse()

        result = system_messages + kept
        logger.info("Trimmed from %d to %d messages (%d -> %d tokens)", len(messages), len(result), total, self._token_counter.estimate_tokens(result))
        return result

    async def trim_with_summary(self, messages: list[Message]) -> list[Message]:
        if not self._summarizer:
            return self.trim(messages)

        total = self._token_counter.estimate_tokens(messages)
        if total <= self._max_tokens:
            return messages

        system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
        non_system = [m for m in messages if m.role != MessageRole.SYSTEM]

        if len(non_system) <= 4:
            return self.trim(messages)

        boundary = max(1, len(non_system) // 3)
        to_summarize = non_system[:boundary]
        recent = non_system[boundary:]

        try:
            summary_text = await self._summarizer.summarize(to_summarize)
            summary_msg = Message(role=MessageRole.SYSTEM, content=f"[Conversation Summary]\n{summary_text}")
            return self.trim(system_messages + [summary_msg] + recent)
        except Exception as e:
            logger.warning("Summarization failed, falling back to trim: %s", e)
            return self.trim(messages)

    def get_token_estimate(self, messages: list[Message]) -> int:
        return self._token_counter.estimate_tokens(messages)


# ═══════════════════════════════════════════════════════════════════════════════
# 上下文跟踪（AgentRuntime 内部使用）
# ═══════════════════════════════════════════════════════════════════════════════

_agent_request_id_var: ContextVar[str] = ContextVar("agent_request_id", default="")
_agent_trace_id_var: ContextVar[str] = ContextVar("agent_trace_id", default="")


def current_agent_request_id() -> str:
    return _agent_request_id_var.get()


def current_agent_trace_id() -> str:
    return _agent_trace_id_var.get()


class _RequestContext:
    def __init__(self, request_id: str, trace_id: str) -> None:
        self.request_id = request_id
        self.trace_id = trace_id
        self._tokens: Any = None

    def __enter__(self) -> _RequestContext:
        self._tokens = (
            _agent_request_id_var.set(self.request_id),
            _agent_trace_id_var.set(self.trace_id),
        )
        return self

    def __exit__(self, *args: object) -> None:
        if self._tokens is not None:
            _agent_request_id_var.reset(self._tokens[0])
            _agent_trace_id_var.reset(self._tokens[1])
            self._tokens = None


# ═══════════════════════════════════════════════════════════════════════════════
# AgentRuntime — 完整的 ReAct Agent
# ═══════════════════════════════════════════════════════════════════════════════

class AgentRuntime:
    _model_limits_applied: bool = False
    _config_lock = threading.Lock()  # 保护类级别配置调整的线程安全

    def __init__(
        self,
        config: AgentConfig,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        planner: BasePlanner | None = None,
        memory: SlidingWindowMemory | None = None,
    ) -> None:
        if not llm_provider:
            raise AgentRuntimeError("llm_provider is required")
        if not tool_registry:
            raise AgentRuntimeError("tool_registry is required")

        self._auto_tune_config(config)

        self._config = config
        self._llm_provider = llm_provider
        self._tool_registry = tool_registry
        self._planner = planner or DefaultPlanner(config)
        self._memory = memory or SlidingWindowMemory(config)
        self._executor = ToolExecutor(tool_registry, config)
        self._state: AgentState | None = None
        self._fsm: StateMachine | None = None
        self._cancelled = False
        self._cancel_lock = threading.Lock()  # 保护 _cancelled 的线程安全
        self._active_count: int = 0
        self._active_lock = asyncio.Lock()
        self._step_hooks: list[Callable[[StepRecord], None]] = []
        self._error_hooks: list[Callable[[str, Exception], None]] = []

    @classmethod
    def _auto_tune_config(cls, config: AgentConfig) -> None:
        """自动调整模型配置，线程安全。"""
        with cls._config_lock:
            if cls._model_limits_applied:
                return
            limits = lookup_model_limits(config.model)
            if limits is None:
                return
            if config.memory_max_tokens == 4000 and config.max_tokens == 4096:
                sane_max_output = min(limits.max_output, 16384)
                sane_memory = limits.max_context // 4
                config.max_tokens = sane_max_output
                config.memory_max_tokens = sane_memory
                logger.info(
                    "Auto-tuned config for model=%s: max_tokens=%d memory_max_tokens=%d",
                    config.model, sane_max_output, sane_memory,
                )
            cls._model_limits_applied = True

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

    @property
    def is_idle(self) -> bool:
        return self._active_count == 0

    def on_step(self, callback: Callable[[StepRecord], None]) -> None:
        self._step_hooks.append(callback)

    def on_error(self, callback: Callable[[str, Exception], None]) -> None:
        self._error_hooks.append(callback)

    def cancel(self) -> None:
        """取消正在运行的 Agent。线程安全。"""
        with self._cancel_lock:
            self._cancelled = True
        if self._state:
            with contextlib.suppress(Exception):
                self._state.set_status(AgentStatus.CANCELLED)

    async def drain(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while self._active_count > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("AgentRuntime drain timeout after %.0fs", timeout)
                return
            await asyncio.sleep(0.1)

    async def _run_loop(
        self, user_message: str, state: AgentState | None,
        on_chunk: Callable[[StreamChunk], Awaitable[None]] | None = None,
    ) -> AsyncIterator[StepRecord]:
        async with self._active_lock:
            self._active_count += 1
        try:
            # 使用锁保护 _cancelled 重置，避免与 cancel() 竞态
            with self._cancel_lock:
                self._cancelled = False
            self._state = state if state is not None else AgentState()
            self._fsm = StateMachine(self._state)

            if self._config.system_prompt:
                self._state.add_message(Message(role=MessageRole.SYSTEM, content=self._config.system_prompt))

            self._state.add_message(Message(role=MessageRole.USER, content=user_message))

            with _RequestContext(request_id=self._state.run_id, trace_id=self._state.session_id):
                logger.info(
                    "AgentRuntime starting: run_id=%s session_id=%s max_steps=%d",
                    self._state.run_id, self._state.session_id, self._config.max_steps,
                )

                try:
                    self._fsm.transition_to(AgentStatus.THINKING)

                    # 检查取消状态时使用锁
                    with self._cancel_lock:
                        is_cancelled = self._cancelled
                    while self._state.steps < self._config.max_steps and not is_cancelled:
                        self._state.increment_step()
                        step_index = self._state.steps
                        trace_id_str = f"{self._state.run_id}.{step_index}"

                        self._state.compact(self._config)

                        logger.info("Step %d starting: trace_id=%s status=%s", step_index, trace_id_str, self._state.status.value)

                        # 在循环内部再次检查取消状态
                        with self._cancel_lock:
                            is_cancelled = self._cancelled
                        if is_cancelled:
                            break

                        try:
                            decision = await self._run_think_phase(trace_id_str, step_index, on_chunk=on_chunk)
                        except Exception as e:
                            logger.error("LLM error at step %d: %s", step_index, e, exc_info=True)
                            self._handle_error(trace_id_str, str(e), e)
                            self._fsm.transition_to(AgentStatus.ERROR)
                            break

                        if decision is None:
                            logger.warning("Step %d produced no decision, breaking", step_index)
                            self._fsm.transition_to(AgentStatus.FINISHED)
                            break

                        last = self._state.last_step
                        if last is not None:
                            yield last

                        if decision.action_type == ActionType.FINISH:
                            self._fsm.transition_to(AgentStatus.FINISHED)
                            logger.info("Agent finished at step %d: %s", step_index, decision.reasoning)
                            break

                        if decision.action_type == ActionType.ACT:
                            await self._run_act_phase(trace_id_str, step_index)
                            last = self._state.last_step
                            if last is not None:
                                yield last
                        elif decision.action_type == ActionType.ERROR:
                            self._fsm.transition_to(AgentStatus.ERROR)
                            break

                    # 最终检查取消状态
                    with self._cancel_lock:
                        is_cancelled = self._cancelled
                    if is_cancelled:
                        self._state.set_status(AgentStatus.CANCELLED)
                        logger.info("Agent cancelled at step %d", self._state.steps)

                    if self._state.steps >= self._config.max_steps and self._state.status == AgentStatus.THINKING:
                        self._state.set_status(AgentStatus.FINISHED)
                        logger.warning("Agent reached max_steps (%d), forced finish", self._config.max_steps)

                except Exception as e:
                    logger.exception("AgentRuntime fatal error: %s", e)
                    self._state.set_status(AgentStatus.ERROR)
                    last_step = self._state.last_step
                    if last_step:
                        last_step.error = str(e)
                    for hook in self._error_hooks:
                        try:
                            hook(self._state.run_id, e)
                        except Exception as hook_exc:
                            logger.warning("Error hook failed during fatal handler: %s", hook_exc)
        finally:
            async with self._active_lock:
                self._active_count -= 1

    async def run(self, user_message: str, state: AgentState | None = None) -> AgentState:
        async for _ in self._run_loop(user_message, state):
            pass
        assert self._state is not None
        return self._state

    async def _run_think_phase(
        self, trace_id: str, step_index: int,
        on_chunk: Callable[[StreamChunk], Awaitable[None]] | None = None,
    ) -> PlannerDecision | None:
        assert self._state is not None
        assert self._fsm is not None
        start = time.monotonic()

        # 1. 先执行内存裁剪（基于 AgentState）
        trimmed = await self._memory.trim_with_summary(self._state.messages)

        # 2. 创建临时 context 供 Pipeline 使用
        ctx = AgentContext(
            request_id=self._state.run_id,
            session_id=self._state.session_id,
            trace_id=trace_id,
            messages=trimmed.copy(),  # 传递副本，避免 Pipeline 修改影响原始数据
        )

        # 3. Pipeline 执行（ContextWindowMiddleware 可能再次裁剪）
        if on_chunk is not None:
            llm_response = await self._run_streaming_think(ctx, on_chunk)
        else:
            llm_response = await self._llm_provider.complete(ctx)

        # 4. 【关键】将 Pipeline 裁剪后的消息同步回 AgentState
        if ctx.metadata.get("context_truncated"):
            logger.info(
                "[%s] Syncing truncated messages back to AgentState: %d → %d messages",
                trace_id, len(self._state.messages), len(ctx.messages),
            )
            self._state.messages = ctx.messages.copy()

        # 5. 添加助手回复到 AgentState
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
            step_index, trace_id, decision.action_type.value, usage.total_tokens, step_record.duration_ms,
        )

        return decision

    async def _run_streaming_think(
        self, ctx: AgentContext,
        on_chunk: Callable[[StreamChunk], Awaitable[None]],
    ) -> LLMResponse:
        content_parts: list[str] = []
        tool_call_chunks: dict[int, dict[str, Any]] = {}
        final_finish_reason = None
        usage = UsageStats()

        async for chunk in self._llm_provider.stream(ctx):
            await on_chunk(chunk)
            if chunk.delta:
                content_parts.append(chunk.delta)
            if chunk.tool_call_delta:
                idx = chunk.tool_call_delta.get("index", 0)
                if idx not in tool_call_chunks:
                    tool_call_chunks[idx] = {"id": "", "name": "", "arguments": ""}
                tc = tool_call_chunks[idx]
                if chunk.tool_call_delta.get("id"):
                    tc["id"] = chunk.tool_call_delta["id"]
                if chunk.tool_call_delta.get("function_name"):
                    tc["name"] = chunk.tool_call_delta["function_name"]
                if chunk.tool_call_delta.get("arguments"):
                    tc["arguments"] += chunk.tool_call_delta["arguments"]
            if chunk.finish_reason:
                final_finish_reason = chunk.finish_reason

        tool_calls = []
        for idx in sorted(tool_call_chunks):
            tc_chunk = tool_call_chunks[idx]
            try:
                args = json.loads(tc_chunk["arguments"]) if tc_chunk["arguments"] else {}
            except (json.JSONDecodeError, ValueError):
                args = {"_raw": tc_chunk["arguments"]}
            tool_calls.append(ToolCall(
                id=tc_chunk["id"],
                name=tc_chunk["name"],
                arguments=args,
            ))

        content = "".join(content_parts) if content_parts else None
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=final_finish_reason,
            usage=usage,
        )

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
        logger.info("Step %d acting: trace_id=%s tool_count=%d", step_index, trace_id, len(tool_calls))

        results = await self._executor.execute_all(tool_calls)

        for r in results:
            self._state.add_message(r.to_message())

        if last_step:
            last_step.tool_results = results
            last_step.duration_ms += (time.monotonic() - start) * 1000

        logger.info("Step %d act complete: trace_id=%s success=%d/%d", step_index, trace_id, sum(1 for r in results if not r.is_error), len(results))

        self._fsm.transition_to(AgentStatus.THINKING)

    def _emit_step(self, step: StepRecord) -> None:
        for hook in self._step_hooks:
            try:
                hook(step)
            except Exception as exc:
                logger.warning("Step hook failed: %s", exc)

    def _handle_error(self, trace_id: str, message: str, exc: Exception) -> None:
        for hook in self._error_hooks:
            try:
                hook(message, exc)
            except Exception as hook_exc:
                logger.warning("Error hook failed: %s", hook_exc)

    async def run_streaming(self, user_message: str, state: AgentState | None = None) -> AsyncIterator[StepRecord]:
        async for step in self._run_loop(user_message, state):
            yield step

    async def run_streaming_text(self, user_message: str, state: AgentState | None = None) -> AsyncIterator[StreamChunk]:
        """
        流式输出文本响应。
        
        使用有界队列防止 OOM：当消费者处理缓慢时，生产者会阻塞等待，
        而不是无限累积 chunks 在内存中。
        """
        # 设置合理的队列大小限制（基于典型流式响应的 chunk 数量）
        MAX_QUEUE_SIZE = 100
        chunk_queue: asyncio.Queue[StreamChunk] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        _SENTINEL: StreamChunk = StreamChunk()  # sentinel marker

        async def _collect(chunk: StreamChunk) -> None:
            # put 会在队列满时阻塞，防止 OOM
            await chunk_queue.put(chunk)

        async def _run() -> None:
            async for _ in self._run_loop(user_message, state, on_chunk=_collect):
                pass
            await chunk_queue.put(_SENTINEL)

        runner = asyncio.create_task(_run())
        try:
            while True:
                chunk = await chunk_queue.get()
                if chunk is _SENTINEL:
                    break
                yield chunk
        finally:
            if not runner.done():
                runner.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runner


# ═══════════════════════════════════════════════════════════════════════════════
# 信号处理 & 优雅关闭
# ═══════════════════════════════════════════════════════════════════════════════

_SHUTDOWN_REQUESTED = False


def shutdown_requested() -> bool:
    return _SHUTDOWN_REQUESTED


def install_signal_handlers(agent: AgentRuntime | None = None, timeout: float = 30.0) -> None:
    global _SHUTDOWN_REQUESTED

    def _handler(signum: int, frame: object) -> None:
        global _SHUTDOWN_REQUESTED
        if _SHUTDOWN_REQUESTED:
            logger.warning("Second signal received, forcing exit")
            raise SystemExit(1)
        _SHUTDOWN_REQUESTED = True
        sig_name = signal.Signals(signum).name
        logger.warning("Received %s, initiating graceful shutdown", sig_name)
        if agent is not None:
            agent.cancel()
        if agent is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    asyncio.ensure_future, agent.drain(timeout)
                )
            except RuntimeError:
                pass

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    logger.info("Signal handlers installed (SIGTERM, SIGINT)")
