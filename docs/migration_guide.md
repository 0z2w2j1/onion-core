# Migration Guide

> Version: 1.0.0 | Updated: 2026-04-26

---

## Migrating from v0.7.x to v0.8.0

### Architecture Consolidation: `src/` Removed

The `src/` package has been removed. All functionality has been consolidated into `onion_core/`.

**What changed:**
- All imports from `src.xxx` must be changed to `onion_core.xxx`
- `AgentStatus`, `ActionType`, `StepRecord`, `AgentConfig`, `AgentState` → `onion_core.models`
- `AgentRuntime`, `StateMachine`, `BasePlanner`, `DefaultPlanner`, `PlannerDecision`, `ToolExecutor`, `SlidingWindowMemory`, `MemorySummarizer` → `onion_core.agent`

**Migration:**
```python
# Old (v0.7.x)
from src.core.agent import AgentRuntime
from src.schema.models import AgentConfig, AgentStatus

# New (v0.8.0)
from onion_core import AgentRuntime, AgentConfig, AgentStatus
from onion_core.agent import SlidingWindowMemory
```

**Note:** `AgentRuntime` now accepts `LLMProvider` instead of `BaseLLMClient`:
```python
from onion_core import AgentRuntime, AgentConfig
from onion_core.providers.openai import OpenAIProvider

runtime = AgentRuntime(
    config=AgentConfig(model="gpt-4"),
    llm_provider=OpenAIProvider(api_key="sk-..."),
    tool_registry=registry,
)
await runtime.run("Hello")
```

---

## Migrating from v0.6.0 to v0.7.0

This guide helps you migrate from Onion Core v0.6.0 to v0.7.0, covering new features, breaking changes, and best practices.

---

## Table of Contents

- [New Features in v0.7.0](#new-features-in-v070)
- [Breaking Changes](#breaking-changes)
- [Migration Steps](#migration-steps)
- [New APIs](#new-apis)
- [Performance Improvements](#performance-improvements)
- [Examples](#examples)

---

## New Features in v0.7.0

### 1. Enhanced Synchronous API

The synchronous API now properly handles event loop conflicts, making it safe to use in environments where an event loop may already be running (e.g., Jupyter notebooks, async frameworks).

**What changed:**
- `run_sync()`, `stream_sync()`, and other sync methods now detect existing event loops
- Automatically falls back to thread pool execution when needed
- No more `RuntimeError: This event loop is already running` errors

**Before (v0.6.0):**
```python
# Could fail in some async contexts
with Pipeline(provider=MyProvider()) as p:
    response = p.run_sync(context)  # RuntimeError in some cases
```

**After (v0.7.0):**
```python
# Works everywhere
with Pipeline(provider=MyProvider()) as p:
    response = p.run_sync(context)  # ✅ Safe in all contexts
```

### 2. Response Cache Middleware

New `ResponseCacheMiddleware` provides automatic caching of LLM responses to reduce latency and costs.

**Features:**
- Configurable TTL (time-to-live)
- LRU eviction strategy
- Multiple cache key strategies (full context, user-only, custom)
- Hit/miss metrics tracking
- Thread-safe implementation

**Usage:**
```python
from onion_core.middlewares import ResponseCacheMiddleware

pipeline.add_middleware(
    ResponseCacheMiddleware(
        ttl_seconds=300,      # Cache for 5 minutes
        max_size=1000,         # Max 1000 entries
        cache_key_strategy="full"  # Use full context for cache key
    )
)
```

### 3. Comprehensive Load Testing

New test suite for performance benchmarking and load testing:
- Concurrent request handling tests
- Cache performance benchmarks
- Rate limiting under load
- Memory usage profiling
- Sync vs Async API comparison

**Run benchmarks:**
```bash
pytest benchmarks/test_performance.py -v --benchmark-only
pytest tests/test_load.py -v
```

---

## Breaking Changes

### None! 🎉

v0.7.0 is **fully backward compatible** with v0.6.0. All existing code will continue to work without modifications.

---

## Migration Steps

### Step 1: Update Dependencies

```bash
pip install --upgrade onion-core
```

Or if installing from source:
```bash
git pull origin main
pip install -e ".[all]"
```

### Step 2: (Optional) Add Response Caching

If you want to benefit from response caching:

```python
from onion_core.middlewares import ResponseCacheMiddleware

async with Pipeline(provider=MyProvider()) as p:
    # Add cache middleware (priority 75, between Observability and Safety)
    p.add_middleware(ResponseCacheMiddleware(ttl_seconds=300))
    
    # Your existing middlewares
    p.add_middleware(ObservabilityMiddleware())
    p.add_middleware(SafetyGuardrailMiddleware())
    
    # ... rest of your code
```

### Step 3: (Optional) Use Enhanced Sync API

If you were experiencing event loop issues with the sync API, they should now be resolved automatically. No code changes needed.

**Before:**
```python
# Might have failed in some contexts
response = pipeline.run_sync(context)
```

**After:**
```python
# Now works everywhere automatically
response = pipeline.run_sync(context)  # ✅ No changes needed
```

---

## New APIs

### ResponseCacheMiddleware

```python
class ResponseCacheMiddleware(BaseMiddleware):
    def __init__(
        self,
        ttl_seconds: float = 300.0,
        max_size: int = 1000,
        cache_key_strategy: str = "full",
    ) -> None:
        """
        Args:
            ttl_seconds: Cache entry lifetime in seconds (default: 300)
            max_size: Maximum cache entries (default: 1000)
            cache_key_strategy: Key generation strategy
                - "full": Full messages + config (default)
                - "user_only": Only user messages
                - "custom": Override _generate_cache_key()
        """
    
    @property
    def hits(self) -> int:
        """Number of cache hits."""
    
    @property
    def misses(self) -> int:
        """Number of cache misses."""
    
    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 - 1.0)."""
    
    def clear_cache(self) -> None:
        """Clear all cached entries."""
    
    def get_cache_size(self) -> int:
        """Get current number of cached entries."""
```

### Enhanced Sync Methods

All sync methods now handle event loop conflicts automatically:

```python
# These methods are now more robust:
pipeline.run_sync(context)
pipeline.stream_sync(context)
pipeline.execute_tool_call_sync(context, tool_call)
pipeline.execute_tool_result_sync(context, result)
pipeline.startup_sync()
pipeline.shutdown_sync()
```

---

## Performance Improvements

### Response Caching Benefits

Typical performance improvements with caching enabled:

| Scenario | Latency Reduction | Cost Savings |
|----------|------------------|--------------|
| Repeated queries | 90-99% | Up to 100% |
| Similar conversations | 50-80% | 50-80% |
| High-traffic endpoints | 70-95% | 70-95% |

**Example:**
```python
# Without cache: ~500ms per request
# With cache (hit): ~5ms per request (100x faster!)
```

### Event Loop Handling

The enhanced sync API eliminates overhead from manual event loop management:

```python
# New approach (automatic, safe)
response = pipeline.run_sync(context)  # ✅ Handles everything
```

---

## Examples

### Example 1: Basic Caching

```python
from onion_core import Pipeline, AgentContext, Message, EchoProvider
from onion_core.middlewares import ResponseCacheMiddleware

async def main():
    cache = ResponseCacheMiddleware(ttl_seconds=600, max_size=500)
    
    async with Pipeline(provider=EchoProvider()) as p:
        p.add_middleware(cache)
        
        ctx = AgentContext(messages=[
            Message(role="user", content="What is AI?")
        ])
        
        # First call: cache miss (~500ms)
        resp1 = await p.run(ctx)
        print(f"Hit rate: {cache.hit_rate:.1%}")  # 0.0%
        
        # Second call: cache hit (~5ms)
        resp2 = await p.run(ctx)
        print(f"Hit rate: {cache.hit_rate:.1%}")  # 50.0%
        
        print(f"Cache size: {cache.get_cache_size()}")  # 1

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### Example 2: Sync API in Flask

```python
from flask import Flask, request, jsonify
from onion_core import Pipeline, AgentContext, Message, OpenAIProvider
from onion_core.middlewares import ResponseCacheMiddleware

app = Flask(__name__)

# Initialize pipeline once
provider = OpenAIProvider(api_key="sk-...")
cache = ResponseCacheMiddleware(ttl_seconds=300)

pipeline = Pipeline(provider=provider)
pipeline.add_middleware(cache)
pipeline.startup_sync()

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    
    ctx = AgentContext(messages=[
        Message(role="user", content=user_message)
    ])
    
    # Now safe to use in Flask (no event loop conflicts)
    response = pipeline.run_sync(ctx)
    
    return jsonify({
        "response": response.content,
        "cached": cache.hits > 0
    })

if __name__ == "__main__":
    app.run(debug=True)
```

### Example 3: Custom Cache Key Strategy

```python
from onion_core.middlewares import ResponseCacheMiddleware

class CustomCacheMiddleware(ResponseCacheMiddleware):
    def _generate_cache_key(self, context):
        """Custom cache key: only consider first message."""
        import hashlib
        import json
        
        if context.messages:
            first_msg = context.messages[0]
            key_data = {
                "role": first_msg.role,
                "content": first_msg.content[:100]  # First 100 chars
            }
        else:
            key_data = {}
        
        return hashlib.md5(
            json.dumps(key_data, sort_keys=True).encode()
        ).hexdigest()

# Usage
pipeline.add_middleware(CustomCacheMiddleware(ttl_seconds=600))
```

### Example 4: Monitoring Cache Performance

```python
import time
from onion_core.middlewares import ResponseCacheMiddleware

cache = ResponseCacheMiddleware(ttl_seconds=300)

async def monitored_request(pipeline, context):
    start = time.perf_counter()
    response = await pipeline.run(context)
    duration = time.perf_counter() - start
    
    print(f"Duration: {duration*1000:.1f}ms")
    print(f"Cache hit rate: {cache.hit_rate:.1%}")
    print(f"Cache size: {cache.get_cache_size()}")
    
    return response

# Periodic cleanup
def cleanup_old_cache(cache: ResponseCacheMiddleware):
    """Clear cache if hit rate drops below threshold."""
    if cache.hit_rate < 0.3 and cache.get_cache_size() > 100:
        cache.clear_cache()
        print("Cache cleared due to low hit rate")
```

---

## Best Practices

### When to Use Caching

✅ **Good candidates:**
- FAQ-style questions with predictable answers
- Static content generation
- Repeated similar queries
- Development/testing environments

❌ **Not suitable:**
- Real-time data (stock prices, weather)
- Personalized responses
- Time-sensitive information
- Creative writing tasks

### Cache Configuration Tips

1. **TTL Selection:**
   ```python
   # Short-lived data: 1-5 minutes
   ResponseCacheMiddleware(ttl_seconds=60)
   
   # Stable content: 1-24 hours
   ResponseCacheMiddleware(ttl_seconds=3600)
   
   # Static content: days/weeks
   ResponseCacheMiddleware(ttl_seconds=86400)
   ```

2. **Cache Size:**
   ```python
   # Low memory: 100-500 entries
   ResponseCacheMiddleware(max_size=100)
   
   # Normal usage: 1000-5000 entries
   ResponseCacheMiddleware(max_size=1000)
   
   # High traffic: 10000+ entries
   ResponseCacheMiddleware(max_size=10000)
   ```

3. **Key Strategy:**
   ```python
   # Precise matching (default)
   ResponseCacheMiddleware(cache_key_strategy="full")
   
   # Broader matching (more hits, less precise)
   ResponseCacheMiddleware(cache_key_strategy="user_only")
   ```

---

## Troubleshooting

### Issue: Cache not working

**Check:**
1. Is the middleware added before Safety/Context middlewares?
2. Are requests truly identical (same messages, same config)?
3. Is TTL too short?

**Solution:**
```python
# Enable debug logging
import logging
logging.getLogger("onion_core.middleware.cache").setLevel(logging.DEBUG)
```

### Issue: High memory usage

**Check:**
1. Is `max_size` set appropriately?
2. Are there many unique requests?

**Solution:**
```python
# Reduce cache size
cache = ResponseCacheMiddleware(max_size=100)

# Or clear periodically
if cache.get_cache_size() > 500:
    cache.clear_cache()
```

### Issue: Stale cached responses

**Check:**
1. Is TTL appropriate for your use case?
2. Does content change frequently?

**Solution:**
```python
# Shorter TTL
cache = ResponseCacheMiddleware(ttl_seconds=60)

# Or manually clear when needed
cache.clear_cache()
```

---

## Support

For questions or issues:
- 📖 [API Reference](api_reference.md)
- 🏗️ [Architecture Docs](architecture.md)
- 🐛 [GitHub Issues](https://github.com/0z2w2j1/onion-core/issues)
- 💬 [Discussions](https://github.com/0z2w2j1/onion-core/discussions)

---

## Summary

v0.7.0 brings:
- ✅ Enhanced sync API (event loop safe)
- ✅ Response caching middleware
- ✅ Comprehensive load testing
- ✅ Better performance monitoring
- ✅ 100% backward compatibility

**Next steps:**
1. Upgrade: `pip install --upgrade onion-core`
2. (Optional) Add caching to improve performance
3. Run benchmarks: `pytest benchmarks/ -v`
4. Monitor cache hit rates in production

Happy coding! 🚀
