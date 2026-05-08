# Provider Contract

`LLMProvider` is the integration boundary between Onion Core and an LLM service.
Provider implementations must follow this contract so middleware behavior stays
predictable across OpenAI, Anthropic, local, domestic, and custom providers.

## Required Interface

Every provider must implement:

```python
from collections.abc import AsyncIterator

from onion_core import AgentContext, LLMProvider, LLMResponse, StreamChunk


class MyProvider(LLMProvider):
    async def complete(self, context: AgentContext) -> LLMResponse:
        ...

    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        ...
```

`cleanup()` is optional, but providers that own network clients, sockets, or
background resources should implement it.

## Input Contract

Providers receive a fully processed `AgentContext`.

Providers may read:

- `context.messages`
- `context.config`
- `context.metadata`
- `context.request_id`
- `context.session_id`
- `context.trace_id`

Providers should not mutate `context.messages` unless they own a documented
normalization step. Middleware is responsible for governance transformations.

## Response Contract

`complete()` must return `LLMResponse`.

Required expectations:

- Set `content` when the model returned text.
- Set `tool_calls` when the model requested tools.
- Set `finish_reason` when the upstream provider exposes one.
- Set `usage` when token usage is available.
- Set `model` to the actual model name when available.
- Preserve the raw upstream response in `raw` only when useful for debugging.

If an upstream provider returns no text and no tool calls, return an
`LLMResponse` with `content=None` or `content=""`, not `None`.

## Streaming Contract

`stream()` must be an async iterator of `StreamChunk`.

Streaming expectations:

- Yield chunks in provider order.
- Use `delta` for text deltas.
- Use `tool_call_delta` for partial tool call data.
- Set `finish_reason` on the final chunk when available.
- Keep `index` monotonic within a stream.
- Raise a provider exception when the upstream stream fails.

Streaming providers should avoid buffering the full response unless the upstream
API does not support incremental output.

## Error Contract

Provider failures should raise `ProviderError` or an `OnionErrorWithCode` with a
provider error code when practical.

Use fatal errors only for caller/configuration problems that retrying cannot
fix. Examples:

- invalid local configuration
- invalid message format
- unsupported tool schema

Use retryable provider errors for transient upstream failures. Examples:

- network interruption
- upstream timeout
- temporary service errors

The pipeline retry policy and circuit breaker depend on this distinction.

## Tool Calls

Providers that support tool calls should normalize upstream tool calls into
`ToolCall`:

```python
ToolCall(
    id="call_123",
    name="search",
    arguments={"query": "onion core"},
)
```

If upstream tool arguments are invalid JSON, preserve the original payload under
a documented key such as `{"_raw": "..."}` rather than dropping it.

## Resource Ownership

If a provider creates its own HTTP client, it should close that client in
`cleanup()`. If a provider receives an externally owned client, it should not
close it.

`Pipeline(..., owns_provider=True)` calls provider cleanup on shutdown. Use
`owns_provider=False` when a provider or client is shared outside the pipeline.

## Provider Test Checklist

New providers should include tests for:

- initialization with default and custom options
- `name` property
- normal `complete()` response
- usage parsing when usage exists and when it is absent
- tool call parsing
- invalid tool call JSON
- upstream API error handling
- normal streaming
- streaming errors
- cleanup behavior when the provider owns resources

Provider tests should mock upstream SDK clients. Real network integration tests
belong in a separate opt-in test module.
