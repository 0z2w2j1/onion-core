"""Tenant budget example.

This example uses only local code. It demonstrates how `BudgetMiddleware`
blocks a tenant after the configured token budget is exhausted.
"""

from __future__ import annotations

import asyncio

from onion_core import AgentContext, EchoProvider, FinishReason, LLMResponse, Pipeline, UsageStats
from onion_core.middlewares import BudgetMiddleware, ObservabilityMiddleware


class UsageEchoProvider(EchoProvider):
    async def complete(self, context: AgentContext) -> LLMResponse:
        user_text = context.messages[-1].text_content
        return LLMResponse(
            content=f"Echo: {user_text}",
            finish_reason=FinishReason.STOP,
            model="budget-demo",
            usage=UsageStats(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )


async def main() -> None:
    budget = BudgetMiddleware(
        max_total_tokens=50,
        window_seconds=3600,
        scope_key="tenant_id",
    )

    async with (
        Pipeline(provider=UsageEchoProvider())
        .add_middleware(ObservabilityMiddleware())
        .add_middleware(budget)
    ) as pipeline:
        first = await pipeline.complete(
            "first request",
            metadata={"tenant_id": "tenant-a"},
        )
        print(first.content)

        try:
            await pipeline.complete(
                "second request",
                metadata={"tenant_id": "tenant-a"},
            )
        except Exception as exc:
            print(f"blocked: {exc}")

        usage = await budget.get_usage("tenant-a")
        print(f"tenant-a used {usage.total_tokens} tokens")


if __name__ == "__main__":
    asyncio.run(main())
