# Debug Middleware Order

This guide shows how to debug and verify middleware execution order in Onion Core pipelines.

## Understanding Middleware Order

Middleware executes in priority order (lowest first):

```
Request Flow:
  Middleware 1 (priority=50) → Middleware 2 (priority=100) → Provider

Response Flow:
  Provider → Middleware 2 (priority=100) → Middleware 1 (priority=50)
```

## Visualizing Execution Order

### Debug Middleware

```python
import logging
from onion_core.base import BaseMiddleware

logger = logging.getLogger(__name__)

class DebugMiddleware(BaseMiddleware):
    """Log middleware execution."""
    
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority
    
    async def process_request(self, ctx):
        logger.info(f"[REQUEST] {self.name} (priority={self.priority})")
        return ctx
    
    async def process_response(self, ctx):
        logger.info(f"[RESPONSE] {self.name} (priority={self.priority})")
        return ctx
```

### Usage

```python
from onion_core import Pipeline

pipeline = Pipeline()
pipeline.add_middleware(DebugMiddleware("Tracing", 50))
pipeline.add_middleware(DebugMiddleware("Metrics", 90))
pipeline.add_middleware(DebugMiddleware("Safety", 200))
pipeline.add_middleware(DebugMiddleware("Context", 300))

# Output will show execution order
await pipeline.run(context)
```

## Common Issues

### Issue 1: Wrong Priority

**Problem**: Middleware executes in unexpected order

**Diagnosis**:

```python
def print_middleware_order(pipeline):
    """Print middleware execution order."""
    middlewares = pipeline.middlewares
    sorted_mw = sorted(middlewares, key=lambda m: m.priority)
    
    print("Middleware execution order:")
    for i, mw in enumerate(sorted_mw, 1):
        print(f"  {i}. {mw.__class__.__name__} (priority={mw.priority})")

print_middleware_order(pipeline)
```

**Solution**: Adjust priorities

```python
# Correct order
pipeline = Pipeline()
pipeline.add_middleware(TracingMiddleware(priority=50))      # Outer layer
pipeline.add_middleware(MetricsMiddleware(priority=90))
pipeline.add_middleware(RateLimitMiddleware(priority=150))
pipeline.add_middleware(SafetyGuardrailMiddleware(priority=200))
pipeline.add_middleware(ContextMiddleware(priority=300))     # Inner layer
```

### Issue 2: Missing Middleware

**Problem**: Some middleware not executing

**Diagnosis**:

```python
class ExecutionTracker:
    """Track which middleware executed."""
    
    def __init__(self):
        self.executed = []
    
    def record(self, middleware_name: str):
        self.executed.append(middleware_name)
    
    def verify(self, expected_middleware: list):
        """Verify all expected middleware executed."""
        missing = set(expected_middleware) - set(self.executed)
        if missing:
            logger.error(f"Missing middleware: {missing}")
        else:
            logger.info("All middleware executed correctly")

tracker = ExecutionTracker()

# Add tracking to each middleware
class TrackedMiddleware(BaseMiddleware):
    def __init__(self, wrapped_middleware, tracker):
        self.wrapped = wrapped_middleware
        self.tracker = tracker
    
    async def process_request(self, request):
        self.tracker.record(self.wrapped.__class__.__name__)
        return await self.wrapped.process_request(request)
```

### Issue 3: Middleware Pipeline Configuration

**Problem**: Middleware doesn't participate in the onion pipeline correctly

**Diagnosis**:

```python
from onion_core.base import BaseMiddleware

class PipelineValidator(BaseMiddleware):
    """Validate middleware is properly configured."""
    
    async def process_request(self, ctx):
        logger.info(f"{self.__class__.__name__} processing request")
        return ctx
```

## Testing Middleware Order

### Unit Test

```python
import pytest
from unittest.mock import Mock
from onion_core.models import AgentContext
from onion_core.base import BaseMiddleware

@pytest.mark.asyncio
async def test_middleware_order():
    """Test that middleware executes in correct order."""
    
    execution_order = []
    
    class OrderTrackingMiddleware(BaseMiddleware):
        def __init__(self, name):
            self.name = name
        
        async def process_request(self, ctx):
            execution_order.append(f"request:{self.name}")
            return ctx
        
        async def process_response(self, ctx):
            execution_order.append(f"response:{self.name}")
            return ctx
    
    # Create pipeline
    from onion_core import Pipeline
    
    pipeline = Pipeline()
    pipeline.add_middleware(OrderTrackingMiddleware("A"))
    pipeline.add_middleware(OrderTrackingMiddleware("B"))
    pipeline.add_middleware(OrderTrackingMiddleware("C"))
    
    # Execute
    ctx = AgentContext(messages=[{"role": "user", "content": "test"}])
    await pipeline.run(ctx)
    
    # Verify order
    expected = [
        "request:A", "request:B", "request:C",
        "response:C", "response:B", "response:A"
    ]
    
    assert execution_order == expected
```

## Performance Impact

### Measure Middleware Overhead

```python
import time

class TimingMiddleware(BaseMiddleware):
    """Measure middleware execution time."""
    
    async def process_request(self, ctx):
        start = time.time()
        duration = time.time() - start
        
        logger.info(
            f"{self.__class__.__name__} took {duration*1000:.2f}ms"
        )
        
        return ctx
```

### Optimize Order

Place fast middleware first, slow middleware last:

```python
# Optimized order
pipeline = Pipeline()
pipeline.add_middleware(TracingMiddleware(priority=50))     # Very fast
pipeline.add_middleware(MetricsMiddleware(priority=90))      # Fast
pipeline.add_middleware(RateLimitMiddleware(priority=150))   # Fast
pipeline.add_middleware(ResponseCacheMiddleware(priority=180))   # Fast (can short-circuit)
pipeline.add_middleware(SafetyGuardrailMiddleware(priority=200)) # Medium
pipeline.add_middleware(ContextMiddleware(priority=300))     # Slower
```

## Best Practices

1. **Document Priorities**: Comment why each priority was chosen
2. **Test Order**: Verify execution order in tests
3. **Monitor Performance**: Track middleware overhead
4. **Keep It Simple**: Avoid too many middleware layers
5. **Use Debug Mode**: Enable logging during development
6. **Validate Chains**: Ensure proper middleware chaining

## Related Topics

- [Pipeline Scheduling](../explanation/pipeline-scheduling.md)
- [Monitor Pipeline Performance](monitor-pipeline-performance.md)
