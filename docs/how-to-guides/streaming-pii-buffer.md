# Streaming PII Buffer Configuration

This guide shows how to configure the streaming PII detection buffer for optimal performance and accuracy.

## Overview

Streaming PII detection processes text in chunks as it arrives from LLM responses. The buffer configuration affects:

- **Detection Accuracy**: Larger buffers provide more context
- **Latency**: Smaller buffers release content faster
- **Memory Usage**: Buffer size impacts memory consumption

## Basic Configuration

```python
from onion_core.middlewares import SafetyGuardrailMiddleware

safety = SafetyGuardrailMiddleware(
    pii_detection=True,
    streaming_buffer_size=100,  # Characters to buffer
    buffer_timeout=1.0  # Seconds before flushing
)
```

## Buffer Size Tuning

### Small Buffer (50 chars)

**Pros**:
- Low latency (< 10ms)
- Minimal memory usage
- Fast content delivery

**Cons**:
- May miss PII spanning multiple chunks
- Higher false negative rate

**Use Case**: Real-time chat, low-latency requirements

```python
safety = SafetyGuardrailMiddleware(
    streaming_buffer_size=50,
    buffer_timeout=0.5
)
```

### Medium Buffer (100 chars) - Default

**Pros**:
- Good balance of accuracy and latency
- Detects most common PII patterns
- Reasonable memory usage

**Cons**:
- Slight latency increase
- May still miss complex patterns

**Use Case**: General purpose applications

```python
safety = SafetyGuardrailMiddleware(
    streaming_buffer_size=100,
    buffer_timeout=1.0
)
```

### Large Buffer (200 chars)

**Pros**:
- High detection accuracy
- Catches complex PII patterns
- Better context awareness

**Cons**:
- Higher latency (50-100ms)
- More memory usage
- Slower content delivery

**Use Case**: High-security applications, compliance requirements

```python
safety = SafetyGuardrailMiddleware(
    streaming_buffer_size=200,
    buffer_timeout=2.0
)
```

## Timeout Configuration

### Short Timeout (0.5s)

Flushes buffer quickly even if not full:

```python
safety = SafetyGuardrailMiddleware(
    buffer_timeout=0.5,
    force_flush_on_timeout=True
)
```

**Best For**: Interactive applications where responsiveness is critical

### Standard Timeout (1.0s)

Balanced approach:

```python
safety = SafetyGuardrailMiddleware(
    buffer_timeout=1.0,
    force_flush_on_timeout=True
)
```

**Best For**: Most use cases

### Long Timeout (2.0s)

Waits longer for more context:

```python
safety = SafetyGuardrailMiddleware(
    buffer_timeout=2.0,
    force_flush_on_timeout=False  # Wait for buffer to fill
)
```

**Best For**: Batch processing, non-interactive scenarios

## Advanced Features

### Overlap Buffer

Maintains overlap between chunks for better detection:

```python
safety = SafetyGuardrailMiddleware(
    streaming_buffer_size=100,
    overlap_size=20,  # Keep last 20 chars from previous chunk
    use_overlap_for_detection=True
)
```

### Pattern-Specific Buffers

Different buffer sizes for different PII types:

```python
safety = SafetyGuardrailMiddleware(
    default_buffer_size=100,
    pattern_buffers={
        'email': 50,      # Emails are short
        'phone': 30,      # Phone numbers are short
        'address': 200,   # Addresses need more context
        'credit_card': 40 # Credit cards have fixed length
    }
)
```

### Adaptive Buffering

Dynamically adjust buffer size based on content:

```python
def adaptive_buffer_size(context: dict) -> int:
    """Adjust buffer size based on conversation context."""
    
    if context.get('high_security'):
        return 200  # Larger buffer for security
    elif context.get('real_time'):
        return 50   # Smaller buffer for speed
    else:
        return 100  # Default

safety = SafetyGuardrailMiddleware(
    buffer_size_strategy=adaptive_buffer_size
)
```

## Performance Monitoring

### Track Buffer Metrics

```python
from onion_core.middlewares import ObservabilityMiddleware

observability = ObservabilityMiddleware()

async def monitor_buffer_performance(buffer_info: dict):
    """Monitor buffer performance metrics."""
    
    logger.info(f"Buffer size: {buffer_info['current_size']}, fill_rate: {buffer_info['fill_rate']}")
```

### Logging Buffer Events

```python
import logging

logger = logging.getLogger(__name__)

def log_buffer_events(event: dict):
    """Log buffer events for debugging."""
    
    if event['type'] == 'flush':
        logger.debug(
            f"Buffer flushed: {event['size']} chars, "
            f"latency={event['latency']:.2f}s, "
            f"reason={event['reason']}"
        )
    elif event['type'] == 'pii_detected':
        logger.info(
            f"PII detected in buffer: {event['pii_type']}, "
            f"position={event['position']}"
        )
```

## Testing Buffer Configuration

### Load Testing

```python
import asyncio
import time

async def test_buffer_performance(buffer_sizes):
    """Test different buffer sizes under load."""
    
    results = []
    
    for size in buffer_sizes:
        safety = SafetyGuardrailMiddleware(streaming_buffer_size=size)
        
        start_time = time.time()
        
        # Simulate streaming response
        for i in range(100):
            chunk = f"This is test chunk {i} with email test{i}@example.com"
            await safety.process_stream_chunk(chunk)
        
        duration = time.time() - start_time
        results.append({
            'buffer_size': size,
            'duration': duration,
            'throughput': 100 / duration
        })
    
    return results

# Run test
sizes = [50, 100, 150, 200]
results = asyncio.run(test_buffer_performance(sizes))

for result in results:
    print(f"Size: {result['buffer_size']}, "
          f"Duration: {result['duration']:.2f}s, "
          f"Throughput: {result['throughput']:.2f} chunks/s")
```

### Accuracy Testing

```python
async def test_detection_accuracy(buffer_size: int) -> float:
    """Test PII detection accuracy for given buffer size."""
    
    test_cases = [
        ("Contact john.doe@example.com", True),
        ("Call me at 123-456-7890", True),
        ("Hello world", False),
    ]
    
    safety = SafetyGuardrailMiddleware(streaming_buffer_size=buffer_size)
    
    correct = 0
    total = len(test_cases)
    
    for text, should_detect in test_cases:
        detected = await safety.contains_pii(text)
        if detected == should_detect:
            correct += 1
    
    return correct / total

# Test different sizes
for size in [50, 100, 200]:
    accuracy = asyncio.run(test_detection_accuracy(size))
    print(f"Buffer size {size}: {accuracy*100:.1f}% accuracy")
```

## Best Practices

1. **Start with Defaults**: Use 100 char buffer and 1s timeout
2. **Monitor Performance**: Track latency and detection rates
3. **Test Edge Cases**: Verify behavior with partial PII
4. **Adjust Based on Use Case**: Security vs. latency tradeoff
5. **Enable Overlap**: Prevent missing PII at chunk boundaries
6. **Log Detections**: Track what's being caught for tuning

## Troubleshooting

### Issue: Missing PII Detection

**Symptom**: Some PII not detected in streaming mode

**Solutions**:
1. Increase buffer size
2. Enable overlap buffer
3. Increase timeout
4. Check pattern definitions

### Issue: High Latency

**Symptom**: Slow response delivery

**Solutions**:
1. Decrease buffer size
2. Reduce timeout
3. Disable force flush
4. Optimize pattern matching

### Issue: Memory Growth

**Symptom**: Memory usage increasing over time

**Solutions**:
1. Set maximum buffer size
2. Implement buffer cleanup
3. Monitor buffer queue length
4. Use streaming redaction

## Related Topics

- [Customize PII Rules](custom-pii-rules.md)
- [Streaming PII Algorithm](../explanation/streaming-pii-algorithm.md)
- [Secure Agent Tutorial](../tutorials/02-secure-agent.md)
