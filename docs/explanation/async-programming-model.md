# Async Programming Model

Onion Core is built on Python's asyncio framework, providing both async and sync APIs. Understanding the async programming model is crucial for effective use.

## Why Async?

Async programming enables:

1. **Concurrency**: Handle multiple requests simultaneously
2. **Efficiency**: Non-blocking I/O operations
3. **Scalability**: Better resource utilization
4. **Performance**: Reduced latency for I/O-bound tasks

## Core Concepts

### Event Loop

The event loop is the heart of asyncio. It schedules and runs async tasks:

```python
import asyncio

async def main():
    # Your async code here
    pass

asyncio.run(main())
```

### Coroutines

Coroutines are async functions defined with `async def`:

```python
async def fetch_data():
    await some_io_operation()
    return result
```

### Await

The `await` keyword pauses execution until the awaited coroutine completes:

```python
result = await fetch_data()
```

## Onion Core's Async Architecture

### Pipeline Execution

The pipeline executes middleware and providers asynchronously:

```python
from onion_core import Pipeline

pipeline = Pipeline(middlewares=[...])
response = await pipeline.execute(request)
```

### Concurrent Tool Calls

Tools can be executed concurrently:

```python
results = await asyncio.gather(
    tool1.execute(),
    tool2.execute(),
    tool3.execute()
)
```

## Sync API Compatibility

Onion Core provides sync wrappers for web frameworks that don't support async:

```python
from onion_core.agent import AgentRuntime

agent = AgentRuntime(config=config)

# Sync method for Flask, Django, etc.
response = agent.run_sync(prompt="Hello")
```

### How Sync Wrappers Work

Sync methods use `asyncio.run()` internally:

```python
def run_sync(self, prompt: str) -> Response:
    return asyncio.run(self.run_async(prompt))
```

## Common Pitfalls

### 1. Blocking the Event Loop

❌ **Bad**: Blocking operations in async code

```python
async def bad_example():
    time.sleep(1)  # Blocks entire event loop!
```

✅ **Good**: Use async sleep

```python
async def good_example():
    await asyncio.sleep(1)
```

### 2. Mixing Sync and Async

❌ **Bad**: Calling async from sync without proper handling

```python
def sync_function():
    await async_function()  # SyntaxError!
```

✅ **Good**: Use asyncio.run()

```python
def sync_function():
    return asyncio.run(async_function())
```

### 3. Not Awaiting Coroutines

❌ **Bad**: Forgetting to await

```python
async def bad():
    result = fetch_data()  # Returns coroutine, not result!
```

✅ **Good**: Always await

```python
async def good():
    result = await fetch_data()
```

## Thread Pool Integration

For CPU-bound tasks, use thread pools:

```python
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)

async def process_data(data):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, cpu_bound_function, data)
    return result
```

## Best Practices

1. **Use Async Throughout**: Prefer async APIs when available
2. **Avoid Blocking**: Never block the event loop
3. **Proper Error Handling**: Use try/except with async code
4. **Timeout Management**: Set timeouts for all async operations
5. **Resource Cleanup**: Use async context managers

## Performance Optimization

### Concurrent Requests

```python
import asyncio

async def handle_multiple_requests(prompts):
    tasks = [agent.run_async(prompt) for prompt in prompts]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

### Batch Processing

```python
async def batch_process(items, batch_size=10):
    for i in range(0, len(items), batch_size):
        batch = items[i:i+batch_size]
        await asyncio.gather(*[process(item) for item in batch])
```

## Debugging Async Code

### Enable Debug Mode

```python
import asyncio
asyncio.run(main(), debug=True)
```

### Use Async Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Trace Execution

```python
import asyncio

async def traced_function():
    print(f"Task {asyncio.current_task()}")
    # ... your code
```

## Related Topics

- [Pipeline Scheduling](pipeline-scheduling.md)
- [Agent State Machine](agent-state-machine.md)
- [Troubleshoot Timeouts](../how-to-guides/troubleshoot-timeouts.md)
