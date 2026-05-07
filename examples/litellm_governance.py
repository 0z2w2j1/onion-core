"""LiteLLM example: keep LiteLLM as the model gateway and use Onion for governance.

Install optional dependencies:

    pip install litellm

Set a provider key supported by LiteLLM, then run:

    python examples/litellm_governance.py
"""

from __future__ import annotations

import asyncio

from onion_core import AgentContext, CallableProvider, Pipeline


async def litellm_call(context: AgentContext) -> str:
    from litellm import acompletion

    response = await acompletion(
        model=context.config.get("model", "gpt-4o-mini"),
        messages=[
            {"role": message.role.value, "content": message.text_content}
            for message in context.messages
        ],
    )
    return str(response.choices[0].message.content)


async def main() -> None:
    async with Pipeline.governed(
        provider=CallableProvider(litellm_call, model="litellm-router"),
        preset="balanced",
        name="litellm-governed",
    ) as pipeline:
        response = await pipeline.complete(
            "Explain how middleware helps LLM applications.",
            config={"model": "gpt-4o-mini"},
            metadata={"tenant_id": "demo"},
        )
        print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
