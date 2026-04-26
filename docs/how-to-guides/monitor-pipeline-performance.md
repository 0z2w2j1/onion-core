# Monitor Pipeline Performance

This guide shows how to monitor and measure Pipeline performance using built-in observability tools.

## Overview

Monitoring Pipeline performance helps you:

- Identify bottlenecks
- Optimize latency
- Track error rates
- Ensure SLA compliance

## Built-in Metrics

### Enable Metrics Collection

```python
from onion_core.middlewares import ObservabilityMiddleware
from onion_core.observability import MetricsCollector

metrics = MetricsCollector()

observability = ObservabilityMiddleware(
    metrics_enabled=True,
    metrics_collector=metrics
)

pipeline = Pipeline(middlewares=[observability])
```

### Key Metrics

| Metric | Description | Type |
|--------|-------------|------|
| `pipeline.request.duration` | Total request time | Histogram |
| `pipeline.requests.total` | Total requests | Counter |
| `pipeline.requests.success` | Successful requests | Counter |
| `pipeline.requests.error` | Failed requests | Counter |
| `pipeline.middleware.duration` | Per-middleware time | Histogram |
| `provider.latency` | Provider response time | Histogram |
| `tokens.total` | Token usage | Counter |

## Custom Monitoring

### Add Timing Middleware

```python
import time
from onion_core.base import BaseMiddleware

class TimingMiddleware(BaseMiddleware):
    """Measure middleware execution time."""
    
    async def process_request(self, request):
        start_time = time.time()
        
        try:
            response = await self.next.process_request(request)
            duration = time.time() - start_time
            
            # Record metric
            metrics.histogram(
                'middleware.duration',
                duration * 1000,  # Convert to ms
                tags={'middleware': self.__class__.__name__}
            )
            
            return response
        except Exception as e:
            duration = time.time() - start_time
            metrics.increment('middleware.errors', tags={
                'middleware': self.__class__.__name__,
                'error': type(e).__name__
            })
            raise
```

### Track Request/Response Sizes

```python
class SizeTrackingMiddleware(BaseMiddleware):
    """Track request and response sizes."""
    
    async def process_request(self, request):
        # Track request size
        request_size = len(str(request))
        metrics.histogram('request.size.bytes', request_size)
        
        response = await self.next.process_request(request)
        
        # Track response size
        response_size = len(str(response))
        metrics.histogram('response.size.bytes', response_size)
        
        return response
```

## Prometheus Integration

### Expose Metrics Endpoint

```python
from prometheus_client import start_http_server, generate_latest

# Start Prometheus metrics server
start_http_server(8000)

@app.get("/metrics")
def metrics_endpoint():
    return Response(content=generate_latest(), media_type="text/plain")
```

### Custom Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT = Counter(
    'onion_requests_total',
    'Total requests',
    ['status', 'provider']
)

REQUEST_DURATION = Histogram(
    'onion_request_duration_seconds',
    'Request duration',
    ['provider']
)

ACTIVE_REQUESTS = Gauge(
    'onion_active_requests',
    'Currently active requests'
)

# Usage in middleware
async def track_prometheus_metrics(request, response):
    with REQUEST_DURATION.labels(provider=request.provider).time():
        ACTIVE_REQUESTS.inc()
        try:
            result = await process(request)
            REQUEST_COUNT.labels(status='success', provider=request.provider).inc()
            return result
        except Exception:
            REQUEST_COUNT.labels(status='error', provider=request.provider).inc()
            raise
        finally:
            ACTIVE_REQUESTS.dec()
```

## Distributed Tracing

### Enable Tracing

```python
from onion_core.middlewares import ObservabilityMiddleware
from opentelemetry import trace

observability = ObservabilityMiddleware(
    tracing_enabled=True,
    tracer=trace.get_tracer("onion-core")
)
```

### Custom Spans

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_with_tracing(request):
    with tracer.start_as_current_span("process_request") as span:
        span.set_attribute("request.model", request.model)
        span.set_attribute("request.prompt_length", len(request.prompt))
        
        try:
            response = await provider.generate(request)
            span.set_attribute("response.tokens", response.usage.total_tokens)
            return response
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            raise
```

## Logging

### Structured Logging

```python
import logging
import json

logger = logging.getLogger(__name__)

class JsonFormatter(logging.Formatter):
    """Format logs as JSON for easy parsing."""
    
    def format(self, record):
        log_entry = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
        }
        
        # Add extra fields
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        if hasattr(record, 'duration'):
            log_entry['duration_ms'] = record.duration
        
        return json.dumps(log_entry)

# Configure logger
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
```

### Log Request Lifecycle

```python
import uuid

class LoggingMiddleware(BaseMiddleware):
    """Log complete request lifecycle."""
    
    async def process_request(self, request):
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        logger.info(
            "Request started",
            extra={
                'request_id': request_id,
                'model': request.model,
                'prompt_length': len(request.prompt)
            }
        )
        
        try:
            response = await self.next.process_request(request)
            duration = time.time() - start_time
            
            logger.info(
                "Request completed",
                extra={
                    'request_id': request_id,
                    'duration_ms': duration * 1000,
                    'response_length': len(response.content)
                }
            )
            
            return response
        except Exception as e:
            duration = time.time() - start_time
            
            logger.error(
                f"Request failed: {e}",
                extra={
                    'request_id': request_id,
                    'duration_ms': duration * 1000,
                    'error': str(e)
                }
            )
            raise
```

## Alerting

### Set Up Alerts

```python
from onion_core.observability import AlertManager

alerts = AlertManager()

# High error rate alert
alerts.add_rule(
    name="high_error_rate",
    condition=lambda: error_rate() > 0.05,  # > 5%
    callback=lambda: send_alert("High error rate detected!")
)

# High latency alert
alerts.add_rule(
    name="high_latency",
    condition=lambda: p95_latency() > 2000,  # > 2s
    callback=lambda: send_alert("High latency detected!")
)

# Check alerts periodically
async def check_alerts():
    while True:
        await alerts.evaluate_all()
        await asyncio.sleep(60)  # Check every minute
```

## Dashboard Example

### Grafana Dashboard JSON

A complete example dashboard is available in the `monitoring/grafana_dashboard.json` file in the repository.

Key panels:

1. **Request Rate**: Requests per second over time
2. **Latency Distribution**: P50, P95, P99 latencies
3. **Error Rate**: Percentage of failed requests
4. **Token Usage**: Tokens consumed over time
5. **Provider Performance**: Compare providers
6. **Middleware Overhead**: Time spent in each middleware

## Best Practices

1. **Monitor Key Metrics**: Focus on latency, errors, and throughput
2. **Set Baselines**: Know what "normal" looks like
3. **Alert on Symptoms**: Not just causes
4. **Use Distributed Tracing**: For complex debugging
5. **Log Structured Data**: Easier to query and analyze
6. **Regular Reviews**: Review metrics weekly

## Related Topics

- [Troubleshoot Timeouts](troubleshoot-timeouts.md)
- [Benchmark Interpretation](../explanation/benchmark-interpretation.md)
- [Monitoring Guide](../monitoring_guide.md)
