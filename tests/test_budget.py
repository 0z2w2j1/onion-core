"""BudgetMiddleware tests."""

from __future__ import annotations

import pytest

from onion_core import (
    AgentContext,
    EchoProvider,
    FinishReason,
    LLMResponse,
    Message,
    Pipeline,
    RateLimitExceeded,
    UsageStats,
)
from onion_core.middlewares import BudgetMiddleware


class UsageProvider(EchoProvider):
    async def complete(self, context: AgentContext) -> LLMResponse:
        return LLMResponse(
            content="ok",
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="gpt-4o",
        )


@pytest.mark.asyncio
async def test_budget_records_usage_by_scope():
    budget = BudgetMiddleware(max_total_tokens=100, scope_key="tenant_id")
    p = Pipeline(provider=UsageProvider()).add_middleware(budget)
    ctx = AgentContext(
        messages=[Message(role="user", content="hello")],
        metadata={"tenant_id": "tenant-a"},
    )

    await p.run(ctx)
    usage = await budget.get_usage("tenant-a")

    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15


@pytest.mark.asyncio
async def test_budget_blocks_when_scope_is_over_limit():
    budget = BudgetMiddleware(max_total_tokens=14, scope_key="tenant_id")
    p = Pipeline(provider=UsageProvider()).add_middleware(budget)
    first = AgentContext(
        messages=[Message(role="user", content="hello")],
        metadata={"tenant_id": "tenant-a"},
    )
    second = AgentContext(
        messages=[Message(role="user", content="hello again")],
        metadata={"tenant_id": "tenant-a"},
    )

    await p.run(first)

    with pytest.raises(RateLimitExceeded, match="Budget exceeded"):
        await p.run(second)
