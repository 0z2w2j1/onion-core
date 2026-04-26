# Distributed Architecture

Onion Core's distributed architecture enables horizontal scaling and high availability across multiple instances.

## Overview

Distributed features include:

- **Distributed Rate Limiting**: Share rate limits across instances
- **Distributed Caching**: Shared cache using Redis
- **Distributed Circuit Breaking**: Coordinated circuit breaker state
- **Leader Election**: For coordinated tasks

## Architecture Components

### Redis as Coordination Backend

Redis provides:

- Atomic operations for rate limiting
- Pub/Sub for real-time coordination
- TTL-based expiration for automatic cleanup
- Persistence for state recovery

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Instance 1  │     │  Instance 2  │     │  Instance 3  │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │    Redis     │
                    └─────────────┘
```

## Consistency Models

### Eventual Consistency

Most distributed features use eventual consistency:

- **Rate Limits**: May allow slight overages during propagation
- **Cache**: Stale reads possible for short periods
- **Circuit Breakers**: State changes propagate within seconds

### Strong Consistency

Some operations require strong consistency:

- **Leader Election**: Using Redis SET NX
- **Distributed Locks**: Redlock algorithm
- **Counter Increments**: Atomic INCR operations

## TOCTOU Problems

Time-of-check to time-of-use (TOCTOU) issues occur when state changes between check and use.

### Example Problem

```python
# Race condition!
if not rate_limiter.is_limited():  # Check
    await process_request()         # Use - might be limited now!
```

### Solution: Atomic Operations

```python
# Atomic check-and-increment
allowed = await redis.eval("""
    local current = redis.call('GET', KEYS[1])
    if not current or tonumber(current) < tonumber(ARGV[1]) then
        redis.call('INCR', KEYS[1])
        redis.call('EXPIRE', KEYS[1], ARGV[2])
        return 1
    end
    return 0
""", [key], [limit, window])
```

## Failure Handling

### Network Partitions

During network partitions:

- **Rate Limiting**: Each partition enforces independently
- **Caching**: Local fallback cache
- **Circuit Breakers**: Operate on local state

### Redis Failures

Graceful degradation:

```python
try:
    await distributed_rate_limit.check()
except RedisConnectionError:
    # Fall back to local rate limiting
    await local_rate_limit.check()
```

## Performance Considerations

### Latency

- Redis RTT: ~1ms (local), ~5ms (cross-region)
- Batch operations when possible
- Use pipelining for multiple commands

### Throughput

- Redis can handle 100K+ ops/sec
- Use connection pooling
- Monitor Redis CPU/memory

## Best Practices

1. **Use Connection Pooling**: Reuse Redis connections
2. **Set Timeouts**: Prevent hanging on Redis failures
3. **Implement Fallbacks**: Local fallbacks for Redis outages
4. **Monitor Redis Health**: Track latency and errors
5. **Use Appropriate TTLs**: Balance freshness and performance
6. **Test Failure Scenarios**: Verify graceful degradation

## Related Topics

- [Configure Distributed Rate Limiting](../how-to-guides/configure-distributed-ratelimit.md)
- [Distributed Consistency](distributed-consistency.md)
