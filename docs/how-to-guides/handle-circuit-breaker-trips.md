# Handle Circuit Breaker Trips

This guide shows how to handle and recover from circuit breaker trips in Onion Core.

## Understanding Circuit Breaker Trips

A circuit breaker "trips" (opens) when a provider fails too many times, preventing further requests to that provider.

## Monitoring Circuit Breaker State

### Check Circuit State

```python
from onion_core.circuit_breaker import CircuitBreaker

circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60
)

# Check current state
state = circuit_breaker.get_state()
print(f"Circuit state: {state}")  # CLOSED, OPEN, or HALF_OPEN
```

### Subscribe to State Changes

```python
def on_circuit_change(old_state, new_state):
    """Callback when circuit state changes."""
    logger.info(f"Circuit breaker: {old_state} → {new_state}")
    
    if new_state == 'OPEN':
        send_alert("Circuit breaker opened!")
    elif new_state == 'CLOSED':
        logger.info("Circuit breaker recovered")

circuit_breaker.on_state_change(on_circuit_change)
```

## Handling Open Circuits

### Graceful Fallback

```python
from onion_core.circuit_breaker import CircuitBreaker
from onion_core.providers import OpenAIProvider

primary = OpenAIProvider(api_key="key1", model="gpt-4")
fallback = OpenAIProvider(api_key="key2", model="gpt-3.5-turbo")
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

async def generate_with_circuit_breaker(context):
    if not cb.is_open():
        try:
            return await primary.complete(context)
        except Exception as e:
            cb.record_failure(e)
            raise

    logger.warning("Primary provider circuit is open, using fallback")
    return await fallback.complete(context)
```

### Queue Requests for Retry

```python
import asyncio
from collections import deque

class RequestQueue:
    """Queue requests when circuit is open."""
    
    def __init__(self):
        self.queue = deque()
        self.processing = False
    
    async def enqueue(self, request):
        """Add request to queue."""
        self.queue.append(request)
        
        if not self.processing:
            asyncio.create_task(self.process_queue())
    
    async def process_queue(self):
        """Process queued requests when circuit closes."""
        self.processing = True
        
        while self.queue:
            if circuit_breaker.is_closed():
                request = self.queue.popleft()
                try:
                    await process_request(request)
                except Exception as e:
                    logger.error(f"Failed to process queued request: {e}")
            else:
                await asyncio.sleep(1)  # Wait for circuit to close
        
        self.processing = False
```

## Recovery Strategies

### Automatic Recovery

Circuit breaker automatically transitions to HALF_OPEN after timeout:

```python
circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,  # Wait 60s before trying again
    half_open_max_calls=3  # Allow 3 test calls
)
```

### Manual Reset

```python
# Force circuit to closed state
circuit_breaker.reset()

# Or force open (for maintenance)
circuit_breaker.force_open()
```

### Gradual Recovery

```python
class GradualRecovery:
    """Gradually increase traffic to recovered provider."""
    
    def __init__(self, circuit_breaker):
        self.circuit_breaker = circuit_breaker
        self.recovery_percentage = 10  # Start with 10%
    
    async def should_use_provider(self):
        """Decide whether to use this provider."""
        if self.circuit_breaker.is_closed():
            return True
        
        if self.circuit_breaker.is_half_open():
            # Randomly allow based on recovery percentage
            return random.randint(1, 100) <= self.recovery_percentage
        
        return False
    
    def increase_traffic(self):
        """Increase traffic as provider proves healthy."""
        self.recovery_percentage = min(100, self.recovery_percentage + 10)
```

## Debugging Circuit Breaker Issues

### Enable Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('onion_core.circuit_breaker')
```

### Track Failure Reasons

```python
class TrackedCircuitBreaker(CircuitBreaker):
    """Track why failures occur."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.failure_reasons = []
    
    def record_failure(self, error: Exception):
        """Record failure with context."""
        reason = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'timestamp': time.time(),
            'provider': self.provider_name
        }
        self.failure_reasons.append(reason)
        
        super().record_failure(error)
    
    def get_failure_analysis(self):
        """Analyze failure patterns."""
        if not self.failure_reasons:
            return "No failures recorded"
        
        # Count by error type
        error_counts = {}
        for reason in self.failure_reasons[-10:]:  # Last 10 failures
            error_type = reason['error_type']
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        return error_counts
```

### Test Circuit Breaker

```python
async def test_circuit_breaker():
    """Test circuit breaker behavior."""
    
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=2)
    
    # Trip the circuit
    for i in range(3):
        try:
            await cb.execute(failing_request)
        except Exception:
            pass
    
    assert cb.is_open(), "Circuit should be open"
    
    # Wait for recovery
    await asyncio.sleep(2)
    
    assert cb.is_half_open(), "Circuit should be half-open"
    
    # Test recovery
    await cb.execute(successful_request)
    assert cb.is_closed(), "Circuit should be closed"
    
    print("✓ Circuit breaker test passed")
```

## Best Practices

1. **Set Appropriate Thresholds**: Don't trip too easily
2. **Monitor Closely**: Alert on circuit state changes
3. **Have Fallbacks**: Always have backup providers
4. **Test Regularly**: Verify circuit breaker works
5. **Tune Recovery Timeout**: Balance between caution and availability
6. **Log Failures**: Track why circuits trip

## Related Topics

- [Circuit Breaker Transitions](../explanation/circuit-breaker-transitions.md)
- [Setup Fallback Providers](setup-fallback-providers.md)
- [Troubleshoot Timeouts](troubleshoot-timeouts.md)
