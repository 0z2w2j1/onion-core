# Threadpool Tuning

Onion Core uses thread pools for CPU-bound operations and sync-to-async bridging. Proper tuning is essential for optimal performance.

## Understanding Thread Pools

### What is a Thread Pool?

A thread pool is a collection of pre-instantiated worker threads ready to execute tasks. Benefits include:

- **Reduced Overhead**: No thread creation/destruction per task
- **Resource Control**: Limit concurrent threads
- **Task Queueing**: Buffer tasks when all threads are busy

### When Onion Core Uses Thread Pools

1. **Sync API Wrappers**: Converting sync calls to async
2. **CPU-bound Operations**: Token counting, text processing
3. **Blocking I/O**: File operations, database queries
4. **Tool Execution**: Running external tools

## Configuration

### Basic Configuration

```python
from onion_core.config import OnionConfig

config = OnionConfig(
    max_workers=10,           # Number of worker threads
    task_queue_size=100,      # Maximum pending tasks
    thread_name_prefix="onion"  # Thread naming
)
```

### Advanced Configuration

```python
from concurrent.futures import ThreadPoolExecutor
import asyncio

# Custom executor with specific settings
executor = ThreadPoolExecutor(
    max_workers=20,
    thread_name_prefix="cpu_bound",
    initializer=worker_init,
    initargs=(config,)
)

# Integrate with event loop
loop = asyncio.get_running_loop()
loop.set_default_executor(executor)
```

## Tuning Strategies

### CPU-Bound Workloads

For CPU-intensive tasks (tokenization, text processing):

**Formula**: `max_workers = CPU_COUNT + 1`

```python
import os

cpu_count = os.cpu_count()
config = OnionConfig(
    max_workers=cpu_count + 1
)
```

**Rationale**: One extra worker handles I/O while CPUs are busy

### I/O-Bound Workloads

For I/O-intensive tasks (API calls, database queries):

**Formula**: `max_workers = CPU_COUNT * 5`

```python
import os

cpu_count = os.cpu_count()
config = OnionConfig(
    max_workers=cpu_count * 5
)
```

**Rationale**: I/O operations spend most time waiting, so more threads can overlap waits

### Mixed Workloads

For applications with both CPU and I/O tasks:

**Formula**: `max_workers = CPU_COUNT * 2`

```python
import os

cpu_count = os.cpu_count()
config = OnionConfig(
    max_workers=cpu_count * 2
)
```

**Rationale**: Balance between CPU utilization and I/O concurrency

## Performance Testing

### Benchmark Different Configurations

```python
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

async def test_threadpool_size(sizes):
    results = []
    
    for size in sizes:
        executor = ThreadPoolExecutor(max_workers=size)
        
        start_time = time.time()
        
        # Run benchmark tasks
        tasks = [
            asyncio.get_running_loop().run_in_executor(executor, cpu_bound_task, i)
            for i in range(100)
        ]
        await asyncio.gather(*tasks)
        
        duration = time.time() - start_time
        results.append((size, duration))
        
        executor.shutdown()
    
    return results

# Test different sizes
sizes = [4, 8, 12, 16, 20, 24]
results = asyncio.run(test_threadpool_size(sizes))

for size, duration in results:
    print(f"Workers: {size}, Duration: {duration:.2f}s")
```

### Monitor Thread Utilization

```python
import threading
import time

def monitor_threads():
    while True:
        active_threads = threading.active_count()
        thread_names = [t.name for t in threading.enumerate()]
        
        print(f"Active threads: {active_threads}")
        print(f"Threads: {thread_names}")
        
        time.sleep(5)

# Run in background
import threading
monitor_thread = threading.Thread(target=monitor_threads, daemon=True)
monitor_thread.start()
```

## Common Issues

### Issue 1: Thread Starvation

**Symptom**: Tasks queue up, high latency

**Cause**: Too few workers for workload

**Solution**: Increase `max_workers`

```python
# Before
config = OnionConfig(max_workers=4)

# After
config = OnionConfig(max_workers=12)
```

### Issue 2: Resource Exhaustion

**Symptom**: High CPU usage, context switching overhead

**Cause**: Too many workers

**Solution**: Decrease `max_workers`

```python
# Before
config = OnionConfig(max_workers=50)

# After
config = OnionConfig(max_workers=16)
```

### Issue 3: Queue Overflow

**Symptom**: `QueueFull` exceptions, rejected tasks

**Cause**: Task queue too small

**Solution**: Increase `task_queue_size` or add backpressure

```python
config = OnionConfig(
    max_workers=10,
    task_queue_size=500  # Increased from default 100
)
```

## Best Practices

### 1. Separate Executors for Different Workloads

```python
cpu_executor = ThreadPoolExecutor(
    max_workers=os.cpu_count() + 1,
    thread_name_prefix="cpu"
)

io_executor = ThreadPoolExecutor(
    max_workers=os.cpu_count() * 5,
    thread_name_prefix="io"
)

# Use appropriate executor
async def process_request(request):
    if request.is_cpu_bound:
        result = await loop.run_in_executor(cpu_executor, process, request)
    else:
        result = await loop.run_in_executor(io_executor, process, request)
```

### 2. Implement Backpressure

```python
import asyncio

class BoundedExecutor:
    def __init__(self, max_workers, max_queue_size):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = asyncio.Semaphore(max_queue_size)
    
    async def submit(self, func, *args):
        async with self.semaphore:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.executor, func, *args)

# Usage
executor = BoundedExecutor(max_workers=10, max_queue_size=100)
result = await executor.submit(cpu_intensive_function, data)
```

### 3. Graceful Shutdown

```python
import signal
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)

def shutdown(signum, frame):
    print("Shutting down executor...")
    executor.shutdown(wait=True)
    print("Executor shut down complete")
    exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
```

### 4. Monitor and Alert

```python
from onion_core.middlewares import ObservabilityMiddleware

observability = ObservabilityMiddleware()

def report_threadpool_metrics():
    active_threads = threading.active_count()
    logger.info("threadpool_metrics", active_threads=active_threads)
    
    if active_threads > WARNING_THRESHOLD:
        logger.warning(f"High thread count: {active_threads}")
    
    if active_threads > CRITICAL_THRESHOLD:
        logger.error(f"Critical thread count: {active_threads}")
```

## Production Recommendations

### Small Scale (< 100 RPS)

```python
config = OnionConfig(
    max_workers=4,
    task_queue_size=50
)
```

### Medium Scale (100-1000 RPS)

```python
config = OnionConfig(
    max_workers=12,
    task_queue_size=200
)
```

### Large Scale (> 1000 RPS)

```python
config = OnionConfig(
    max_workers=24,
    task_queue_size=500
)
```

## Debugging

### Enable Thread Logging

```python
import logging
import threading

# Log thread creation and destruction
original_init = threading.Thread.__init__

def logged_init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    logger.debug(f"Thread created: {self.name}")

threading.Thread.__init__ = logged_init
```

### Track Executor Statistics

```python
from concurrent.futures import ThreadPoolExecutor
import time

class MonitoredExecutor(ThreadPoolExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tasks_submitted = 0
        self.tasks_completed = 0
        self.total_wait_time = 0
    
    def submit(self, fn, *args, **kwargs):
        self.tasks_submitted += 1
        start_time = time.time()
        
        future = super().submit(fn, *args, **kwargs)
        
        future.add_done_callback(lambda f: self._on_complete(start_time))
        return future
    
    def _on_complete(self, start_time):
        self.tasks_completed += 1
        wait_time = time.time() - start_time
        self.total_wait_time += wait_time
    
    def get_stats(self):
        return {
            'submitted': self.tasks_submitted,
            'completed': self.tasks_completed,
            'pending': self.tasks_submitted - self.tasks_completed,
            'avg_wait_time': self.total_wait_time / max(1, self.tasks_completed)
        }
```

## Related Topics

- [Memory Management](memory-management.md)
- [Pipeline Scheduling](pipeline-scheduling.md)
- [Async Programming Model](async-programming-model.md)
- [Benchmark Interpretation](benchmark-interpretation.md)
