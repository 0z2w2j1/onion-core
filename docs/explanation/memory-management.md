# Memory Management

Effective memory management is critical for long-running LLM applications. This document covers strategies for managing memory in Onion Core.

## Memory Usage Patterns

### Typical Memory Consumers

1. **Conversation History**: Growing message lists
2. **Cache Entries**: Stored responses and embeddings
3. **Context Windows**: Buffered text for processing
4. **Tool Results**: Data returned from tool executions
5. **Observability Data**: Logs, metrics, and traces

## Memory Monitoring

### Programmatic Monitoring

```python
import psutil
import os

def get_memory_usage():
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    
    return {
        'rss_mb': memory_info.rss / 1024 / 1024,  # Resident Set Size
        'vms_mb': memory_info.vms / 1024 / 1024,  # Virtual Memory Size
        'percent': process.memory_percent()
    }

# Usage
usage = get_memory_usage()
print(f"Memory: {usage['rss_mb']:.2f}MB ({usage['percent']:.1f}%)")
```

### Integration with Observability

```python
from onion_core.middlewares import ObservabilityMiddleware

observability = ObservabilityMiddleware()

async def track_memory():
    usage = get_memory_usage()
    logger.info("memory_usage", rss_mb=usage['rss_mb'], percent=usage['percent'])
```

## Memory Optimization Strategies

### 1. Context Window Management

Limit conversation history size:

```python
from onion_core.middlewares import ContextWindowMiddleware

context_middleware = ContextWindowMiddleware(
    max_tokens=8000,
    max_messages=50,
    strategy="hybrid"
)
```

### 2. Cache Eviction

Implement TTL and size limits:

```python
from onion_core.middlewares import ResponseCacheMiddleware

cache = ResponseCacheMiddleware(
    ttl=300,  # 5 minutes
    max_size=1000,  # Maximum entries
    eviction_policy="lru"  # Least Recently Used
)
```

### 3. Streaming Processing

Process data in chunks instead of loading entire responses:

```python
async def stream_response(agent, ctx):
    async for chunk in agent.run_streaming(ctx):
        # Process each chunk immediately
        yield chunk
        # Chunk is garbage collected after yielding
```

### 4. Lazy Loading

Load data only when needed:

```python
class LazyToolRegistry:
    def __init__(self):
        self._tools = {}
        self._loaded = set()
    
    def get_tool(self, name):
        if name not in self._loaded:
            self._tools[name] = self._load_tool(name)
            self._loaded.add(name)
        return self._tools[name]
```

## Garbage Collection

### Manual GC Triggers

For memory-intensive operations:

```python
import gc

async def process_large_batch(items):
    results = []
    for i, item in enumerate(items):
        result = await process(item)
        results.append(result)
        
        # Trigger GC every 100 items
        if i % 100 == 0:
            gc.collect()
    
    return results
```

### Weak References

Avoid circular references:

```python
import weakref

class AgentRuntime:
    def __init__(self):
        self.pipeline = Pipeline()
        # Use weak reference to avoid circular dependency
        self.pipeline.agent_ref = weakref.ref(self)
```

## Memory Leaks Detection

### Common Leak Sources

1. **Unclosed Connections**: Database or HTTP connections
2. **Growing Collections**: Lists/dicts that never shrink
3. **Circular References**: Objects referencing each other
4. **Global State**: Accumulating data in module-level variables

### Detection Techniques

#### Track Object Count

```python
import sys
import gc

def count_objects_by_type():
    counts = {}
    for obj in gc.get_objects():
        type_name = type(obj).__name__
        counts[type_name] = counts.get(type_name, 0) + 1
    
    # Print top 20 most common types
    for type_name, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:20]:
        print(f"{type_name}: {count}")
```

#### Memory Profiling

```python
import tracemalloc

def profile_memory():
    tracemalloc.start()
    
    # ... your code ...
    
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')
    
    print("[ Top 10 memory consumers ]")
    for stat in top_stats[:10]:
        print(stat)
```

## Configuration Recommendations

### Small Scale (< 100 RPS)

```python
config = {
    'context_window': {
        'max_tokens': 4000,
        'max_messages': 20
    },
    'cache': {
        'max_size': 500,
        'ttl': 300
    },
    'concurrency': {
        'max_workers': 4
    }
}
```

### Medium Scale (100-1000 RPS)

```python
config = {
    'context_window': {
        'max_tokens': 8000,
        'max_messages': 50
    },
    'cache': {
        'max_size': 2000,
        'ttl': 600
    },
    'concurrency': {
        'max_workers': 10
    }
}
```

### Large Scale (> 1000 RPS)

```python
config = {
    'context_window': {
        'max_tokens': 16000,
        'max_messages': 100
    },
    'cache': {
        'max_size': 10000,
        'ttl': 900
    },
    'concurrency': {
        'max_workers': 20
    }
}
```

## Best Practices

### 1. Set Memory Limits

```python
import resource

# Set memory limit to 2GB
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 * 1024 * 1024, -1))
```

### 2. Implement Health Checks

```python
def memory_health_check():
    usage = get_memory_usage()
    
    if usage['percent'] > 90:
        return {"status": "unhealthy", "reason": "High memory usage"}
    elif usage['percent'] > 75:
        return {"status": "warning", "reason": "Moderate memory usage"}
    else:
        return {"status": "healthy"}
```

### 3. Use Generators

Prefer generators over lists for large datasets:

```python
# Bad: Loads all items into memory
def get_all_items():
    return [process(item) for item in huge_dataset]

# Good: Processes one item at a time
def get_all_items():
    for item in huge_dataset:
        yield process(item)
```

### 4. Clear Unused Data

```python
async def process_request(request):
    try:
        result = await handle(request)
        return result
    finally:
        # Clean up temporary data
        del request.large_payload
```

## Troubleshooting

### High Memory Usage

**Symptoms**: Memory continuously grows, OOM errors

**Steps**:
1. Profile memory with `tracemalloc`
2. Check for unclosed resources
3. Review cache size and TTL
4. Monitor object counts
5. Check for circular references

### Memory Spikes

**Symptoms**: Sudden memory increase during specific operations

**Steps**:
1. Identify the operation causing spike
2. Implement streaming/batching
3. Add memory limits
4. Use lazy loading

### Memory Leaks

**Symptoms**: Memory grows even with constant load

**Steps**:
1. Run long-duration test
2. Take memory snapshots
3. Compare snapshots to find leaks
4. Fix identified issues
5. Verify fix with another test

## Related Topics

- [Context Management Tradeoffs](context-management-tradeoffs.md)
- [Pipeline Scheduling](pipeline-scheduling.md)
- [Threadpool Tuning](threadpool-tuning.md)
