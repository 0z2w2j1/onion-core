# API Stability Policy

This page defines which Onion Core APIs are stable enough for downstream
applications to depend on, and which APIs may still change between minor
versions.

Onion Core follows semantic versioning for stable public APIs after the
`1.1.0` stable release. During beta releases, breaking changes should still be
rare, documented, and accompanied by migration notes.

## Stability Levels

| Level | Meaning | Compatibility expectation |
| --- | --- | --- |
| Stable | Recommended for production integrations. | No breaking changes in patch releases. Breaking changes require a minor or major release and migration notes. |
| Beta | Usable, but the API may change while the design is being refined. | Breaking changes are allowed in minor releases and must be documented. |
| Internal | Implementation detail. | No compatibility guarantee. |

## Stable Public API

These imports are the primary supported surface:

```python
from onion_core import (
    AgentContext,
    CallableProvider,
    EchoProvider,
    LLMProvider,
    LLMResponse,
    Message,
    Pipeline,
    StreamChunk,
)

from onion_core.middlewares import (
    BudgetMiddleware,
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    ResponseCacheMiddleware,
    SafetyGuardrailMiddleware,
)
```

The stable path is centered on:

- `Pipeline`
- `LLMProvider`
- `CallableProvider`
- `AgentContext`, `Message`, `LLMResponse`, `StreamChunk`
- Built-in governance middlewares
- Provider adapters under `onion_core.providers`
- Configuration objects under `onion_core.config`
- Error codes under `onion_core.error_codes`

## Beta API

The agent runtime is intentionally useful but not the main product surface.
Treat these APIs as beta unless a release note states otherwise:

- `AgentLoop`
- `AgentRuntime`
- `StateMachine`
- `DefaultPlanner`
- `ToolExecutor`
- `SlidingWindowMemory`
- `MemorySummarizer`

These APIs may change as the project learns from real agent workloads. For
production governance integrations, prefer `Pipeline.governed()`.

## Internal API

Do not depend on private names, helper modules, or metadata keys that begin with
an underscore. Examples:

- `onion_core._validation`
- private `Pipeline` methods such as `_run_request()`
- context metadata keys such as `_safety_buf_*`
- private attributes such as `provider._model`

Middleware authors may read documented metadata keys, but should avoid private
keys because they can change without notice.

## Deprecation Process

When a stable API needs to change:

1. Add a deprecation note to the docstring and documentation.
2. Keep the old API working for at least one minor release when practical.
3. Add a changelog entry with the replacement.
4. Add or update tests that cover both the old and new behavior during the
   deprecation window.
5. Remove the deprecated API only in a release that clearly documents the
   breaking change.

## Versioning Rules

- Patch release: bug fixes, documentation, non-breaking behavior fixes.
- Minor release: new APIs, new providers, documented beta API changes.
- Major release: breaking changes to stable APIs.
- Beta/pre-release: allowed to refine public behavior, but changes must be
  called out in `CHANGELOG.md`.

## Recommended Import Style

Applications should import stable APIs from `onion_core` or documented
subpackages:

```python
from onion_core import Pipeline, CallableProvider
from onion_core.middlewares import SafetyGuardrailMiddleware
from onion_core.providers.openai import OpenAIProvider
```

Avoid importing from private modules or depending on undocumented side effects.
