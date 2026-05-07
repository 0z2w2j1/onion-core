"""Onion Core - token and cost budget middleware."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from ..base import BaseMiddleware
from ..error_codes import ErrorCode
from ..models import AgentContext, LLMResponse, RateLimitExceeded, StreamChunk, UsageStats
from ..observability.metrics import calculate_cost


@dataclass(frozen=True)
class BudgetUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class _BudgetEntry:
    timestamp: float
    usage: BudgetUsage


class BudgetMiddleware(BaseMiddleware):
    """
    Sliding-window token and cost budget enforcement.

    The middleware is intentionally lightweight and in-memory. For multi-process
    deployments, use it as a local guardrail and put authoritative quota tracking
    in a shared backend or upstream gateway.
    """

    priority: int = 125
    is_mandatory: bool = True

    def __init__(
        self,
        *,
        max_prompt_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        max_total_tokens: int | None = None,
        max_cost_usd: float | None = None,
        window_seconds: float = 3600.0,
        scope_key: str = "tenant_id",
        max_scopes: int = 10_000,
        estimate_prompt_tokens: bool = True,
        custom_pricing: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self._max_prompt_tokens = max_prompt_tokens
        self._max_completion_tokens = max_completion_tokens
        self._max_total_tokens = max_total_tokens
        self._max_cost_usd = max_cost_usd
        self._window_seconds = window_seconds
        self._scope_key = scope_key
        self._max_scopes = max_scopes
        self._estimate_prompt_tokens = estimate_prompt_tokens
        self._custom_pricing = custom_pricing
        self._usage_windows: OrderedDict[str, deque[_BudgetEntry]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def process_request(self, context: AgentContext) -> AgentContext:
        scope = self._resolve_scope(context)
        now = time.monotonic()
        estimated_prompt = (
            self._estimate_context_tokens(context) if self._estimate_prompt_tokens else 0
        )

        async with self._lock:
            window = self._get_window(scope)
            self._prune_window(window, now)
            current = self._sum_window(window)
            self._raise_if_exceeded(context, scope, current, estimated_prompt)

        context.metadata["budget_scope"] = scope
        context.metadata["budget_prompt_tokens_used"] = current.prompt_tokens
        context.metadata["budget_completion_tokens_used"] = current.completion_tokens
        context.metadata["budget_total_tokens_used"] = current.total_tokens
        context.metadata["budget_cost_usd_used"] = round(current.cost_usd, 8)
        if self._max_total_tokens is not None:
            context.metadata["budget_total_tokens_remaining"] = max(
                self._max_total_tokens - current.total_tokens - estimated_prompt,
                0,
            )
        if self._max_cost_usd is not None:
            context.metadata["budget_cost_usd_remaining"] = max(
                self._max_cost_usd - current.cost_usd,
                0.0,
            )
        return context

    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        usage = self._usage_from_response(context, response)
        if usage.total_tokens <= 0 and usage.cost_usd <= 0:
            return response

        scope = context.metadata.get("budget_scope", self._resolve_scope(context))
        async with self._lock:
            window = self._get_window(scope)
            self._prune_window(window, time.monotonic())
            window.append(_BudgetEntry(timestamp=time.monotonic(), usage=usage))
        return response

    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk:
        return chunk

    async def get_usage(self, scope: str) -> BudgetUsage:
        async with self._lock:
            window = self._usage_windows.get(scope, deque())
            self._prune_window(window, time.monotonic())
            return self._sum_window(window)

    def _resolve_scope(self, context: AgentContext) -> str:
        value = context.metadata.get(self._scope_key)
        if value is None:
            value = context.config.get(self._scope_key)
        return str(value or context.session_id)

    def _get_window(self, scope: str) -> deque[_BudgetEntry]:
        if scope in self._usage_windows:
            self._usage_windows.move_to_end(scope)
            return self._usage_windows[scope]
        if len(self._usage_windows) >= self._max_scopes:
            self._usage_windows.popitem(last=False)
        self._usage_windows[scope] = deque()
        return self._usage_windows[scope]

    def _prune_window(self, window: deque[_BudgetEntry], now: float) -> None:
        cutoff = now - self._window_seconds
        while window and window[0].timestamp < cutoff:
            window.popleft()

    def _sum_window(self, window: deque[_BudgetEntry]) -> BudgetUsage:
        prompt = sum(entry.usage.prompt_tokens for entry in window)
        completion = sum(entry.usage.completion_tokens for entry in window)
        total = sum(entry.usage.total_tokens for entry in window)
        cost = sum(entry.usage.cost_usd for entry in window)
        return BudgetUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cost_usd=cost,
        )

    def _raise_if_exceeded(
        self,
        context: AgentContext,
        scope: str,
        current: BudgetUsage,
        estimated_prompt_tokens: int,
    ) -> None:
        checks = [
            ("prompt_tokens", self._max_prompt_tokens, current.prompt_tokens + estimated_prompt_tokens),
            ("completion_tokens", self._max_completion_tokens, current.completion_tokens),
            ("total_tokens", self._max_total_tokens, current.total_tokens + estimated_prompt_tokens),
        ]
        for label, limit, value in checks:
            if limit is not None and value > limit:
                raise RateLimitExceeded(
                    f"Budget exceeded for scope '{scope}': {label} {value} > {limit}",
                    error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
                )

        if self._max_cost_usd is not None and current.cost_usd >= self._max_cost_usd:
            raise RateLimitExceeded(
                f"Budget exceeded for scope '{scope}': cost ${current.cost_usd:.6f} >= ${self._max_cost_usd:.6f}",
                error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            )

        context.metadata["budget_estimated_prompt_tokens"] = estimated_prompt_tokens

    def _usage_from_response(
        self, context: AgentContext, response: LLMResponse
    ) -> BudgetUsage:
        stats = response.usage or UsageStats(
            prompt_tokens=int(context.metadata.get("budget_estimated_prompt_tokens", 0)),
            completion_tokens=0,
            total_tokens=int(context.metadata.get("budget_estimated_prompt_tokens", 0)),
        )
        model = response.model or str(context.metadata.get("model", "default"))
        cost = calculate_cost(
            model,
            stats.prompt_tokens,
            stats.completion_tokens,
            custom_pricing=self._custom_pricing,
        )
        return BudgetUsage(
            prompt_tokens=stats.prompt_tokens,
            completion_tokens=stats.completion_tokens,
            total_tokens=stats.total_tokens,
            cost_usd=cost,
        )

    def _estimate_context_tokens(self, context: AgentContext) -> int:
        override = context.metadata.get("estimated_prompt_tokens")
        if isinstance(override, int):
            return max(override, 0)
        total_chars = sum(len(message.text_content) for message in context.messages)
        return max(int(total_chars / 4), 1) if total_chars else 0
