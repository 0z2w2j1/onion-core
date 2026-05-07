# Wrap an Existing LLM Call

Use `CallableProvider` when your application already has a working LLM SDK/client
and you only want Onion Core middleware around that call.

```python
from onion_core import AgentContext, CallableProvider, Pipeline

async def existing_llm_call(ctx: AgentContext) -> str:
    # Call your existing OpenAI, Anthropic, LiteLLM, vLLM, or internal client here.
    prompt = ctx.messages[-1].text_content
    return await my_client.complete(prompt)

pipeline = Pipeline.governed(
    provider=CallableProvider(existing_llm_call, model="internal-chat"),
    preset="balanced",
)

response = await pipeline.complete("Summarize this incident report")
print(response.content)
```

`Pipeline.governed(..., preset="balanced")` installs the default embeddable
governance stack:

- `ResponseCacheMiddleware`
- `ObservabilityMiddleware`
- `RateLimitMiddleware`
- `SafetyGuardrailMiddleware`
- `ContextWindowMiddleware`

Use `preset="minimal"` when you only want logging, safety, and context control.
Use `preset="production"` with `OnionConfig` when you also want budget, metrics,
or tracing configured explicitly.
