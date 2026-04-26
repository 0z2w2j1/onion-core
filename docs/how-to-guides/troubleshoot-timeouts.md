# Troubleshoot Timeouts

This guide helps you diagnose and resolve timeout issues in Onion Core.

## Understanding Timeouts

Timeouts occur when operations take longer than expected. Common causes:

- Slow provider responses
- Network latency
- Resource contention
- Configuration issues

## Timeout Configuration

### Pipeline Timeout

```python
from onion_core.config import PipelineConfig

config = PipelineConfig(
    timeout=30.0,  # Total pipeline execution timeout
    provider_timeout=25.0,  # Provider-specific timeout
    middleware_timeout=5.0  # Middleware processing timeout
)
```

### Provider Timeout

```python
from onion_core.providers import OpenAIProvider

provider = OpenAIProvider(
    api_key="your-key",
    model="gpt-4",
    timeout=30.0,  # Request timeout
    connect_timeout=5.0  # Connection timeout
)
```

## Diagnosing Timeouts

### Enable Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('onion_core')
```

### Add Timing Middleware

```python
import time
from onion_core.base import BaseMiddleware

class TimeoutDiagnosticMiddleware(BaseMiddleware):
    """Diagnose where time is spent."""
    
    async def process_request(self, request):
        start = time.time()
        
        try:
            response = await self.next.process_request(request)
            duration = time.time() - start
            
            if duration > 10:  # Log slow requests
                logger.warning(
                    f"Slow request: {duration:.2f}s",
                    extra={'duration': duration}
                )
            
            return response
        except Exception as e:
            duration = time.time() - start
            logger.error(
                f"Request failed after {duration:.2f}s: {e}",
                extra={'duration': duration, 'error': str(e)}
            )
            raise
```

## Common Timeout Scenarios

### Scenario 1: Provider Timeout

**Symptom**: `TimeoutError: Provider request timed out`

**Causes**:
- Provider API is slow
- Network issues
- Large prompt/response

**Solutions**:

1. **Increase Timeout**:
```python
provider = OpenAIProvider(timeout=60.0)  # Increase from 30s
```

2. **Optimize Prompt**:
```python
# Reduce prompt size
from onion_core.middlewares import ContextWindowMiddleware

context = ContextWindowMiddleware(max_tokens=4000)  # Limit context
```

3. **Use Faster Model**:
```python
provider = OpenAIProvider(model="gpt-3.5-turbo")  # Faster than GPT-4
```

### Scenario 2: Middleware Timeout

**Symptom**: `TimeoutError: Middleware processing timed out`

**Causes**:
- Slow middleware logic
- External service calls
- Complex computations

**Solutions**:

1. **Profile Middleware**:
```python
import time

class ProfilingMiddleware(BaseMiddleware):
    async def process_request(self, request):
        start = time.time()
        response = await self.next.process_request(request)
        duration = time.time() - start
        
        logger.info(f"{self.__class__.__name__}: {duration*1000:.2f}ms")
        return response
```

2. **Optimize Slow Middleware**:
```python
# Cache expensive operations
from functools import lru_cache

@lru_cache(maxsize=1000)
def expensive_computation(data):
    return result
```

3. **Set Per-Middleware Timeouts**:
```python
middleware = SafetyMiddleware(timeout=2.0)  # 2s timeout for safety checks
```

### Scenario 3: Connection Timeout

**Symptom**: `ConnectionError: Failed to connect within timeout`

**Causes**:
- Network issues
- DNS resolution problems
- Firewall blocking

**Solutions**:

1. **Check Connectivity**:
```bash
curl -v https://api.openai.com/v1
```

2. **Increase Connect Timeout**:
```python
provider = OpenAIProvider(connect_timeout=10.0)  # Increase from 5s
```

3. **Use Retry Logic**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def connect_with_retry():
    return await provider.generate(prompt)
```

### Scenario 4: Concurrent Request Timeout

**Symptom**: Timeouts only under high load

**Causes**:
- Thread pool exhaustion
- Resource contention
- Rate limiting

**Solutions**:

1. **Increase Concurrency**:
```python
from onion_core.config import ConcurrencyConfig

config = ConcurrencyConfig(
    max_workers=20,  # Increase from 10
    task_queue_size=200  # Increase queue size
)
```

2. **Implement Backpressure**:
```python
import asyncio

semaphore = asyncio.Semaphore(10)  # Max 10 concurrent requests

async def limited_request(prompt):
    async with semaphore:
        return await agent.run_async(prompt)
```

3. **Monitor Resource Usage**:
```python
import psutil

def check_resources():
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory().percent
    
    if cpu > 80 or memory > 80:
        logger.warning(f"High resource usage: CPU={cpu}%, Memory={memory}%")
```

## Timeout Handling Strategies

### Graceful Degradation

```python
from onion_core.manager import ProviderManager

manager = ProviderManager()

async def generate_with_fallback(prompt):
    providers = manager.get_all_providers()
    
    for provider in providers:
        try:
            return await asyncio.wait_for(
                provider.generate(prompt),
                timeout=provider.timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Provider {provider.name} timed out, trying next...")
            continue
    
    raise TimeoutError("All providers timed out")
```

### Circuit Breaker Integration

```python
from onion_core.middlewares import CircuitBreakerMiddleware

circuit_breaker = CircuitBreakerMiddleware(
    failure_threshold=5,
    recovery_timeout=60
)

# Automatically stop using failing providers
pipeline = Pipeline(middlewares=[circuit_breaker])
```

### Timeout with Cancellation

```python
async def run_with_cancellation(prompt, timeout=30.0):
    try:
        return await asyncio.wait_for(
            agent.run_async(prompt),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.error(f"Request timed out after {timeout}s")
        # Clean up resources
        await cleanup()
        raise
```

## Monitoring Timeouts

### Track Timeout Metrics

```python
from onion_core.observability import MetricsCollector

metrics = MetricsCollector()

async def track_timeouts(request, error):
    if isinstance(error, asyncio.TimeoutError):
        metrics.increment('timeouts.total', tags={
            'provider': request.provider,
            'model': request.model
        })
```

### Alert on Timeout Spike

```python
def detect_timeout_spike():
    """Detect unusual timeout patterns."""
    recent_timeouts = metrics.get('timeouts.last_hour')
    baseline = metrics.get('timeouts.baseline')
    
    if recent_timeouts > baseline * 2:
        send_alert(f"Timeout spike detected: {recent_timeouts} timeouts in last hour")
```

## Best Practices

1. **Set Realistic Timeouts**: Based on provider SLAs
2. **Implement Retries**: With exponential backoff
3. **Use Circuit Breakers**: Prevent cascading failures
4. **Monitor Closely**: Track timeout rates
5. **Test Under Load**: Verify behavior at scale
6. **Have Fallbacks**: Alternative providers or responses

## Related Topics

- [Handle Circuit Breaker Trips](handle-circuit-breaker-trips.md)
- [Setup Fallback Providers](setup-fallback-providers.md)
- [Troubleshoot Performance](monitor-pipeline-performance.md)
