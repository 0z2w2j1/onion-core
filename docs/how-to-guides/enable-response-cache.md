# Enable Response Cache

This guide shows how to enable and configure response caching to improve performance and reduce costs.

## Why Cache?

- **Performance**: Faster response times
- **Cost Reduction**: Fewer API calls
- **Rate Limit Protection**: Stay within API limits
- **Consistency**: Same input produces same output

## Basic Caching

### In-Memory Cache

```python
from onion_core.middlewares import ResponseCacheMiddleware
from onion_core import Pipeline

cache = ResponseCacheMiddleware(
    ttl=300,  # Time to live in seconds (5 minutes)
    max_size=1000  # Maximum number of cached items
)

pipeline = Pipeline()
pipeline.add_middleware(cache)
```

### Usage

```python
# First call - hits the API
response1 = await pipeline.run(context)

# Second call with same request - returns cached response
response2 = await pipeline.run(context)  # Much faster!
```

## Advanced Configuration

### Custom TTL per Request

```python
cache = ResponseCacheMiddleware(
    default_ttl=300,
    ttl_strategy=lambda request: 600 if request.is_important else 60
)
```

### Cache Key Customization

```python
def custom_cache_key(request):
    """Generate custom cache key."""
    return f"{request.model}:{request.prompt_hash}:{request.temperature}"

cache = ResponseCacheMiddleware(
    key_generator=custom_cache_key
)
```

## Distributed Caching with Redis

### Installation

```bash
pip install redis
```

### Configuration

```python
from onion_core.middlewares import DistributedCacheMiddleware

distributed_cache = DistributedCacheMiddleware(
    redis_url="redis://localhost:6379",
    ttl=300,
    prefix="onion_cache"
)

pipeline = Pipeline()
pipeline.add_middleware(distributed_cache)
```

### Benefits

- **Shared Across Instances**: Multiple servers share cache
- **Persistence**: Cache survives restarts
- **Scalability**: Handle more cache entries

## Cache Invalidation

### Manual Invalidation

```python
# Clear specific cache entry
await cache.invalidate(cache_key)

# Clear all cache
await cache.clear()

# Clear by pattern
await cache.invalidate_pattern("gpt-4:*")
```

### Automatic Invalidation

```python
cache = ResponseCacheMiddleware(
    ttl=300,
    auto_invalidate_on_error=True,  # Clear cache on errors
    max_age=3600  # Absolute maximum age
)
```

## Monitoring Cache Performance

### Cache Metrics

```python
from onion_core.middlewares import ObservabilityMiddleware

observability = ObservabilityMiddleware()

async def track_cache_performance(request, cached):
    if cached:
        logger.info("Cache hit")
    else:
        logger.info("Cache miss")
```

### Logging

```python
import logging

logger = logging.getLogger(__name__)

async def logged_cache_lookup(request):
    cache_key = generate_cache_key(request)
    
    cached = await cache.get(cache_key)
    if cached:
        logger.info(f"Cache hit for key: {cache_key}")
        return cached
    
    logger.debug(f"Cache miss for key: {cache_key}")
    response = await provider.complete(context)
    await cache.set(cache_key, response)
    return response
```

## Cache Strategies

### Write-Through Cache

```python
async def write_through_cache(request):
    """Always write to cache after fetching."""
    cache_key = generate_cache_key(request)
    
    # Check cache first
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    # Fetch from provider
    response = await provider.complete(context)
    
    # Write to cache
    await cache.set(cache_key, response)
    
    return response
```

### Read-Aside Cache

```python
async def read_aside_cache(request):
    """Only cache successful responses."""
    cache_key = generate_cache_key(request)
    
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    try:
        response = await provider.complete(context)
        # Only cache successful responses
        if response.success:
            await cache.set(cache_key, response)
        return response
    except Exception as e:
        logger.error(f"Provider error: {e}")
        raise
```

## Best Practices

1. **Set Appropriate TTL**: Balance freshness and performance
2. **Monitor Hit Rate**: Aim for > 50% hit rate
3. **Invalidate on Updates**: Clear cache when data changes
4. **Use Distributed Cache**: For multi-instance deployments
5. **Limit Cache Size**: Prevent memory issues
6. **Cache Selectively**: Not all requests benefit from caching

## Related Topics

- [Distributed Cache](../api/middlewares/cache.md)
- [Performance Optimization](../explanation/benchmark-interpretation.md)
- [Memory Management](../explanation/memory-management.md)
