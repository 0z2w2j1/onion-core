# Degradation Strategy

Onion Core implements a multi-layered degradation strategy to maintain service availability during failures.

## Degradation Levels

### Level 1: Retry with Backoff

First line of defense against transient failures.

```python
import asyncio

async def generate_with_retry(context):
    for attempt in range(3):
        try:
            return await provider.complete(context)
        except Exception:
            if attempt == 2:
                raise
            delay = 2 ** attempt
            await asyncio.sleep(delay)
```

### Level 2: Fallback Providers

Switch to alternative providers when primary fails.

```python
from onion_core import Pipeline

pipeline = Pipeline(
    provider=primary_provider,
    fallback_providers=[fallback_provider]
)

# Automatically uses fallback on failure
response = await pipeline.run(ctx)
```

### Level 3: Reduced Quality

Use cheaper/faster models when premium models unavailable.

```python
def select_model(availability: dict) -> str:
    """Select model based on availability."""
    if availability.get('gpt-4'):
        return 'gpt-4'
    elif availability.get('gpt-3.5-turbo'):
        return 'gpt-3.5-turbo'
    else:
        return 'local-model'
```

### Level 4: Cached Responses

Serve cached responses when all providers fail.

```python
async def generate_with_cache_fallback(context):
    try:
        return await provider.complete(context)
    except ProviderError:
        # Try to serve from cache
        cached = await cache.get(context)
        if cached:
            logger.info("Serving cached response")
            cached.is_cached = True
            return cached
        
        raise
```

### Level 5: Graceful Error Messages

When all else fails, provide helpful error messages.

```python
try:
    response = await agent.run(ctx)
except AllProvidersDownError:
    return Response(
        content="We're experiencing technical difficulties. "
                "Please try again in a few minutes.",
        is_degraded=True
    )
```

## Circuit Breaker Integration

Circuit breakers prevent cascading failures:

```python
from onion_core.circuit_breaker import CircuitBreaker

circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60
)

# Automatically stops using failing providers
pipeline = Pipeline(
    provider=primary_provider,
    circuit_breaker=circuit_breaker
)
```

## Monitoring Degradation

Track degradation events:

```python
from onion_core.middlewares import ObservabilityMiddleware

observability = ObservabilityMiddleware()

def track_degradation(level: int, reason: str):
    """Track degradation events."""
    logger.warning("degradation_event", level=level, reason=reason)
    
    if level >= 3:
        send_alert(f"High degradation level: {level}")
```

## Best Practices

1. **Implement All Levels**: Defense in depth
2. **Monitor Closely**: Track degradation frequency
3. **Test Regularly**: Verify fallbacks work
4. **Communicate Status**: Inform users of degradation
5. **Auto-Recovery**: Return to normal when possible
6. **Document Procedures**: Clear runbooks for incidents

## Related Topics

- [Setup Fallback Providers](../how-to-guides/setup-fallback-providers.md)
- [Handle Circuit Breaker Trips](../how-to-guides/handle-circuit-breaker-trips.md)
- [Troubleshoot Timeouts](../how-to-guides/troubleshoot-timeouts.md)
