# Degradation Strategy

Onion Core implements a multi-layered degradation strategy to maintain service availability during failures.

## Degradation Levels

### Level 1: Retry with Backoff

First line of defense against transient failures.

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def generate_with_retry(prompt):
    return await provider.generate(prompt)
```

### Level 2: Fallback Providers

Switch to alternative providers when primary fails.

```python
from onion_core.manager import ProviderManager

manager = ProviderManager()
manager.add_provider("primary", primary_provider, priority=1)
manager.add_provider("fallback", fallback_provider, priority=2)

# Automatically uses fallback on failure
response = await manager.generate(prompt)
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
async def generate_with_cache_fallback(prompt):
    try:
        return await provider.generate(prompt)
    except ProviderError:
        # Try to serve from cache
        cached = await cache.get(prompt)
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
    response = await agent.run_async(prompt)
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
circuit_breaker = CircuitBreakerMiddleware(
    failure_threshold=5,
    recovery_timeout=60
)

# Automatically stops using failing providers
pipeline = Pipeline(middlewares=[circuit_breaker])
```

## Monitoring Degradation

Track degradation events:

```python
from onion_core.observability import MetricsCollector

metrics = MetricsCollector()

def track_degradation(level: int, reason: str):
    """Track degradation events."""
    metrics.increment('degradation.events', tags={
        'level': level,
        'reason': reason
    })
    
    if level >= 3:
        send_alert(f"High degradation level: {level}")
```

## Configuration

```python
from onion_core.config import DegradationConfig

config = DegradationConfig(
    max_retries=3,
    retry_delay=1.0,
    enable_fallback=True,
    enable_cache_fallback=True,
    max_degradation_level=4
)
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
