# Production Deployment Checklist

This guide describes how to run Onion Core in production-like environments. It
focuses on operational choices rather than local quick-start code.

## Choose the Right Topology

Use the default in-memory middlewares when:

- the application runs as a single process
- rate limits and cache entries do not need to be shared
- a process restart can safely reset middleware state

Use Redis-backed distributed middlewares when:

- the application has multiple worker processes
- the application has multiple service instances
- rate limits must be shared across instances
- cache and circuit breaker state should survive process restarts

The distributed middlewares prioritize availability and operational simplicity.
They do not provide strong global consistency for every race condition.

## Start With the Governed Pipeline

For most applications, use `Pipeline.governed()` instead of assembling every
middleware manually.

```python
from onion_core import Pipeline
from onion_core.providers.openai import OpenAIProvider

provider = OpenAIProvider(api_key="...", model="gpt-4o-mini")

pipeline = Pipeline.governed(
    provider=provider,
    preset="production",
    name="chat-api",
)
```

Recommended presets:

| Preset | Use when |
| --- | --- |
| `minimal` | local development or internal tools |
| `balanced` | early production integrations with cache and rate limit |
| `production` | production services with budget, metrics, or tracing enabled |
| `strict` | environments where input PII masking is required |

## Configure Timeouts

Set both provider and total timeouts. Provider timeouts protect upstream calls;
total timeouts bound the entire middleware chain.

```python
from onion_core import OnionConfig

config = OnionConfig()
config.pipeline.provider_timeout = 30.0
config.pipeline.total_timeout = 45.0
config.pipeline.max_retries = 2
```

Use a total timeout that is larger than the provider timeout plus retry delay.

## Decide Fail-Open vs Fail-Closed

Distributed middleware may be configured to allow or deny requests when Redis is
unavailable.

Fail closed when the middleware enforces security, budget, or hard quota
requirements. Fail open when availability is more important and another control
plane exists upstream.

Typical choices:

| Middleware | Default recommendation |
| --- | --- |
| Distributed rate limit | fail closed for public APIs, fail open for internal tools |
| Distributed cache | fail closed only if cache integrity is required |
| Distributed circuit breaker | fail open when provider fallback exists |

## Isolate Tenants

For multi-tenant services:

- set `context.metadata["tenant_id"]`
- configure `BudgetMiddleware(scope_key="tenant_id")`
- use cache namespaces per application or environment
- include model/provider identity in cache keys

`ResponseCacheMiddleware` already includes provider and model identity in cache
keys. Keep tenant-specific data in messages, config, namespace, or metadata that
your cache strategy includes.

## Enable Observability

Production services should enable structured logs, metrics, and tracing where
the deployment platform supports them.

```python
config.observability.enable_metrics = True
config.observability.enable_tracing = True
config.observability.service_name = "chat-api"
```

At minimum, preserve these fields in logs:

- `request_id`
- `trace_id`
- `session_id`
- `pipeline`
- `provider_name`
- error code and error type

## Manage Provider Lifecycle

Let the pipeline own providers when each pipeline creates its own provider:

```python
pipeline = Pipeline.governed(provider=provider, owns_provider=True)
```

Use `owns_provider=False` when a provider or HTTP client is shared by a larger
application lifecycle:

```python
pipeline = Pipeline.governed(provider=shared_provider, owns_provider=False)
```

Shared providers must be closed by the application at shutdown.

## Protect Streaming Responses

Streaming responses should have:

- `provider_timeout` or `total_timeout`
- `max_stream_chunks`
- `SafetyGuardrailMiddleware` enabled when output PII masking is required

Do not disable the stream chunk limit for public endpoints.

## Deployment Readiness Checklist

- CI passes tests, lint, type check, and package build.
- `Pipeline.governed()` is used for the main request path.
- Provider and total timeouts are set.
- Retry count is bounded.
- Circuit breaker is enabled for remote providers.
- Redis-backed middlewares are used for multi-instance quotas.
- Observability is enabled and request identifiers reach logs.
- Security and rate limit exceptions are mapped to safe HTTP responses.
- Provider clients are cleaned up on shutdown.
- Real provider credentials are loaded from secrets, not config files.

## HTTP Error Mapping

Recommended HTTP status mapping:

| Exception | HTTP status |
| --- | --- |
| `SecurityException` | 400 or 403 |
| `RateLimitExceeded` | 429 |
| `CircuitBreakerError` | 503 |
| `ProviderError` | 502 or 503 |
| `ValidationError` | 400 |
| timeout errors | 504 |

Return generic user-facing messages for security and provider failures. Keep
detailed diagnostics in structured logs.
