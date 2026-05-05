# Benchmark Interpretation

Understanding benchmark results is crucial for optimizing Onion Core performance. This guide explains how to interpret common benchmarks.

## Key Metrics

### Latency

**Definition**: Time taken to process a request (milliseconds)

**Types**:
- **P50 (Median)**: 50% of requests are faster than this value
- **P95**: 95% of requests are faster than this value
- **P99**: 99% of requests are faster than this value

**Interpretation**:
- Lower is better
- P95 and P99 reveal tail latency issues
- Large gap between P50 and P99 indicates inconsistency

### Throughput

**Definition**: Number of requests processed per second (RPS)

**Interpretation**:
- Higher is better
- Should scale with concurrent users
- Plateau indicates resource bottleneck

### Error Rate

**Definition**: Percentage of failed requests

**Interpretation**:
- Should be < 1% in production
- Spikes indicate instability
- Track error types separately

### Resource Usage

**CPU**: Processor utilization percentage
**Memory**: RAM usage in MB/GB
**Network**: Bandwidth consumption

## Running Benchmarks

### Basic Benchmark

```bash
pytest benchmarks/test_performance.py -v
```

### Load Test

```powershell
.\benchmarks\scripts\load_test.ps1 -ConcurrentUsers 100 -Duration 60
```

### Custom Scenario

```python
import asyncio
from onion_core import AgentRuntime

async def benchmark_scenario():
    agent = AgentRuntime(config=config)
    
    start_time = time.time()
    tasks = [agent.run(ctx) for _ in range(100)]
    results = await asyncio.gather(*tasks)
    end_time = time.time()
    
    total_time = end_time - start_time
    rps = 100 / total_time
    print(f"Throughput: {rps:.2f} RPS")
```

## Interpreting Results

### Example Output

```
Performance Test Results:
=========================
Requests: 1000
Concurrency: 10
Duration: 30s

Latency:
  P50: 120ms
  P95: 250ms
  P99: 450ms
  Max: 1200ms

Throughput: 33.3 RPS

Error Rate: 0.2%

Resource Usage:
  CPU: 45%
  Memory: 512MB
```

### Analysis

**Good Signs**:
✅ P50 < 200ms (fast median response)
✅ P95 < 500ms (acceptable tail latency)
✅ Error rate < 1% (reliable)
✅ CPU < 70% (headroom for spikes)

**Warning Signs**:
⚠️ P99 > 1000ms (poor tail latency)
⚠️ Error rate > 5% (unreliable)
⚠️ CPU > 90% (resource constrained)
⚠️ Large P50-P99 gap (inconsistent performance)

## Common Patterns

### Pattern 1: Increasing Latency Over Time

**Symptom**: Latency gradually increases during test

**Causes**:
- Memory leak
- Connection pool exhaustion
- Cache growth without eviction

**Solution**:
- Profile memory usage
- Tune connection pool size
- Implement cache eviction policies

### Pattern 2: Throughput Plateau

**Symptom**: RPS stops increasing despite more concurrency

**Causes**:
- CPU bottleneck
- I/O saturation
- Thread pool exhaustion

**Solution**:
- Optimize CPU-bound operations
- Increase I/O capacity
- Tune thread pool size

### Pattern 3: Spike in P99 Latency

**Symptom**: P99 much higher than P50

**Causes**:
- Garbage collection pauses
- Network timeouts
- Resource contention

**Solution**:
- Optimize memory allocation
- Implement circuit breakers
- Use connection pooling

## Optimization Strategies

### 1. Middleware Optimization

Profile middleware overhead:

```python
import time

class TimingMiddleware:
    async def process_request(self, request):
        start = time.time()
        response = await self.next.process_request(request)
        duration = time.time() - start
        print(f"Middleware took {duration*1000:.2f}ms")
        return response
```

### 2. Connection Pooling

Reuse connections to reduce latency:

```python
from onion_core.providers import OpenAIProvider

provider = OpenAIProvider(
    api_key="...",
    connection_pool_size=20,  # Tune based on load
    connection_timeout=5.0
)
```

### 3. Caching

Reduce redundant API calls:

```python
from onion_core.middlewares import ResponseCacheMiddleware

cache = ResponseCacheMiddleware(
    ttl=300,  # 5 minutes
    max_size=1000
)
```

### 4. Concurrency Tuning

Adjust thread pool size:

```python
from onion_core.config import OnionConfig

config = OnionConfig(
    max_workers=10,
    task_queue_size=100
)
```

## Benchmark Best Practices

### 1. Realistic Workloads

- Use production-like prompts
- Simulate realistic user patterns
- Include various request sizes

### 2. Warm-up Period

```python
# Run warm-up requests before measuring
for _ in range(10):
    await agent.run(warmup_ctx)

# Now run actual benchmark
start_benchmark()
```

### 3. Multiple Runs

Run benchmarks multiple times and average:

```python
results = []
for i in range(5):
    result = run_benchmark()
    results.append(result)

avg_rps = sum(r.rps for r in results) / len(results)
print(f"Average RPS: {avg_rps}")
```

### 4. Monitor Resources

```python
import psutil

def monitor_resources():
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory().used / 1024 / 1024  # MB
    print(f"CPU: {cpu}%, Memory: {memory}MB")
```

## Comparison Baselines

### Local Development

| Metric | Target |
|--------|--------|
| P50 Latency | < 200ms |
| P95 Latency | < 500ms |
| Throughput | > 20 RPS |
| Error Rate | < 1% |

### Production

| Metric | Target |
|--------|--------|
| P50 Latency | < 150ms |
| P95 Latency | < 300ms |
| Throughput | > 100 RPS |
| Error Rate | < 0.1% |

## Tools

### Built-in Benchmarks

Located in `benchmarks/` directory:
- `test_performance.py`: Basic performance tests
- `test_middleware_latency.py`: Middleware overhead
- `scripts/load_test.ps1`: Load testing script

### External Tools

- **wrk**: HTTP benchmarking tool
- **Apache Bench (ab)**: Simple load testing
- **Locust**: Distributed load testing
- **k6**: Modern load testing platform

## Related Topics

- [Pipeline Scheduling](pipeline-scheduling.md)
- [Troubleshoot Timeouts](../how-to-guides/troubleshoot-timeouts.md)
- [Monitoring Guide](../monitoring_guide.md)
