# Implement Tool Deduplication

This guide shows how to prevent duplicate tool calls in Agent loops.

## The Problem

Agents may call the same tool multiple times with identical arguments, wasting resources and time.

## Basic Deduplication

### Simple Cache-Based Approach

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_tool_call(tool_name: str, args_hash: str):
    """Cache tool call results."""
    # Execute tool
    return execute_tool(tool_name, args_hash)

def deduplicate_tool_call(tool_name: str, args: dict):
    """Deduplicate tool calls."""
    args_hash = hash(frozenset(args.items()))
    return cached_tool_call(tool_name, args_hash)
```

### Time-Based Deduplication

```python
import time
from collections import defaultdict

class TimeBasedDeduplicator:
    """Prevent duplicate calls within time window."""
    
    def __init__(self, window_seconds=60):
        self.window = window_seconds
        self.recent_calls = defaultdict(list)
    
    def should_execute(self, tool_name: str, args: dict) -> bool:
        """Check if tool call should be executed."""
        key = f"{tool_name}:{hash(frozenset(args.items()))}"
        now = time.time()
        
        # Clean old entries
        self.recent_calls[key] = [
            t for t in self.recent_calls[key]
            if now - t < self.window
        ]
        
        # Check if recently called
        if self.recent_calls[key]:
            return False
        
        # Record this call
        self.recent_calls[key].append(now)
        return True
```

## Advanced Deduplication

### Semantic Deduplication

Detect semantically similar requests:

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class SemanticDeduplicator:
    """Detect semantically similar tool calls."""
    
    def __init__(self, similarity_threshold=0.95):
        self.threshold = similarity_threshold
        self.vectorizer = TfidfVectorizer()
        self.call_history = []
    
    def is_duplicate(self, tool_name: str, query: str) -> bool:
        """Check if query is semantically similar to recent calls."""
        
        if not self.call_history:
            return False
        
        # Vectorize queries
        queries = [h['query'] for h in self.call_history] + [query]
        vectors = self.vectorizer.fit_transform(queries)
        
        # Compare with recent calls
        recent_vectors = vectors[-2:-1]  # Last call
        current_vector = vectors[-1:]  # Current call
        
        similarity = cosine_similarity(current_vector, recent_vectors).max()
        
        return similarity > self.threshold
    
    def record_call(self, tool_name: str, query: str, result):
        """Record tool call for future comparison."""
        self.call_history.append({
            'tool': tool_name,
            'query': query,
            'result': result,
            'timestamp': time.time()
        })
        
        # Keep only recent history
        cutoff = time.time() - 3600  # 1 hour
        self.call_history = [h for h in self.call_history if h['timestamp'] > cutoff]
```

### Result Caching

```python
import hashlib
import json

class ResultCache:
    """Cache tool results for identical inputs."""
    
    def __init__(self, max_size=1000, ttl=300):
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl
    
    def _make_key(self, tool_name: str, args: dict) -> str:
        """Generate cache key."""
        content = json.dumps({
            'tool': tool_name,
            'args': args
        }, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, tool_name: str, args: dict):
        """Get cached result if available."""
        key = self._make_key(tool_name, args)
        
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry['timestamp'] < self.ttl:
                return entry['result']
            else:
                del self.cache[key]
        
        return None
    
    def set(self, tool_name: str, args: dict, result):
        """Cache tool result."""
        key = self._make_key(tool_name, args)
        
        # Evict old entries if cache is full
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache, key=lambda k: self.cache[k]['timestamp'])
            del self.cache[oldest_key]
        
        self.cache[key] = {
            'result': result,
            'timestamp': time.time()
        }
```

## Integration with Agent

### Middleware Approach

```python
from onion_core.base import BaseMiddleware

class ToolDeduplicationMiddleware(BaseMiddleware):
    """Prevent duplicate tool calls."""
    
    def __init__(self):
        super().__init__()
        self.deduplicator = TimeBasedDeduplicator(window_seconds=60)
        self.result_cache = ResultCache()
    
    async def on_tool_call(self, context, tool_call):
        """Intercept tool calls and deduplicate."""
        tool_name = tool_call.name
        args = tool_call.arguments
        
        # Check cache first
        cached_result = self.result_cache.get(tool_name, args)
        if cached_result is not None:
            logger.info(f"Using cached result for {tool_name}")
            context.metadata["_cached_result"] = cached_result
            return tool_call
        
        # Check if duplicate
        if not self.deduplicator.should_execute(tool_name, args):
            logger.warning(f"Duplicate tool call blocked: {tool_name}")
            raise DuplicateToolCallError("Duplicate call detected")
        
        return tool_call
    
    async def on_tool_result(self, context, result):
        """Cache successful results."""
        if result.error is None:
            self.result_cache.set(
                result.tool_name,
                result.arguments,
                result
            )
        return result
```

### Agent Loop Integration

```python
from onion_core.agent import AgentLoop

class DedupAgentLoop(AgentLoop):
    """Agent loop with built-in deduplication."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tool_cache = ResultCache()
    
    async def execute_tool(self, tool_name: str, args: dict):
        """Execute tool with deduplication."""
        
        # Check cache
        cached = self.tool_cache.get(tool_name, args)
        if cached:
            logger.debug(f"Cache hit for {tool_name}")
            return cached
        
        # Execute tool
        result = await super().execute_tool(tool_name, args)
        
        # Cache result
        self.tool_cache.set(tool_name, args, result)
        
        return result
```

## Monitoring

### Track Deduplication Metrics

```python
import logging

logger = logging.getLogger(__name__)

def track_deduplication(cache_hits: int, cache_misses: int, duplicates_blocked: int):
    """Track deduplication effectiveness."""
    
    hit_rate = cache_hits / (cache_hits + cache_misses) if (cache_hits + cache_misses) > 0 else 0
    logger.info(
        "Deduplication stats",
        extra={
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "duplicates_blocked": duplicates_blocked,
            "hit_rate": hit_rate,
        }
    )
```

## Testing

### Unit Tests

```python
import pytest

def test_time_based_deduplication():
    dedup = TimeBasedDeduplicator(window_seconds=1)
    
    # First call should execute
    assert dedup.should_execute("search", {"query": "test"}) == True
    
    # Second call within window should be blocked
    assert dedup.should_execute("search", {"query": "test"}) == False
    
    # Different args should execute
    assert dedup.should_execute("search", {"query": "different"}) == True

def test_result_cache():
    cache = ResultCache(ttl=1)
    
    # Cache miss
    assert cache.get("tool", {"arg": "value"}) is None
    
    # Set and get
    cache.set("tool", {"arg": "value"}, "result")
    assert cache.get("tool", {"arg": "value"}) == "result"
```

## Best Practices

1. **Use Multiple Strategies**: Combine time-based and result caching
2. **Set Appropriate TTLs**: Balance freshness and efficiency
3. **Monitor Hit Rates**: Track deduplication effectiveness
4. **Handle Edge Cases**: Differentiate between similar but distinct calls
5. **Clear Cache Periodically**: Prevent memory growth
6. **Log Deduplication Events**: For debugging and optimization

## Related Topics

- [Prevent Agent Loops](prevent-agent-loops.md)
- [Agent State Machine](../explanation/agent-state-machine.md)
