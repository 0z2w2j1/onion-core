# Onion Core - Monitoring & Alerting Guide

> Version: 0.7.4 | Updated: 2026-04-26

This guide provides comprehensive instructions for monitoring Onion Core in production environments, including Prometheus metrics, Grafana dashboards, and Alertmanager rules.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prometheus Metrics](#prometheus-metrics)
3. [Grafana Dashboard Setup](#grafana-dashboard-setup)
4. [Alertmanager Rules](#alertmanager-rules)
5. [SLO/SLI Definitions](#slosli-definitions)
6. [Health Check Endpoints](#health-check-endpoints)
7. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────┐
│  Application     │
│  (Onion Core)    │
└────────┬─────────┘
         │ Exposes /metrics endpoint
         ▼
┌─────────────────┐      Scrape every 15s      ┌──────────────────┐
│   Prometheus     │ ◄──────────────────────── │  onion_core app   │
│                  │                            │  :8080/metrics    │
└────────┬─────────┘                            └──────────────────┘
         │ Query
         ▼
┌─────────────────┐
│    Grafana       │ ← Import dashboard from monitoring/grafana_dashboard.json
│  (Visualization) │
└────────┬─────────┘
         │ Alert Rules
         ▼
┌─────────────────┐
│  Alertmanager    │ → Email/Slack/PagerDuty
└─────────────────┘
```

---

## Prometheus Metrics

Onion Core exposes the following metrics via `MetricsMiddleware`:

### Request Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `onion_requests_total` | Counter | `pipeline_name`, `model`, `finish_reason`, `status` | Total number of requests |
| `onion_request_duration_seconds` | Histogram | `pipeline_name`, `model` | Request latency distribution |
| `onion_active_requests` | Gauge | `pipeline_name` | Currently active requests |

### Token Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `onion_tokens_total` | Counter | `pipeline_name`, `model`, `type` (prompt/completion) | Total tokens consumed |

### Tool Call Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `onion_tool_calls_total` | Counter | `pipeline_name`, `tool_name`, `status` | Tool call success/failure |

### Cache Metrics (if using ResponseCacheMiddleware)

Cache hit/miss statistics are available via `ResponseCacheMiddleware.hits`, `.misses`, and `.hit_rate` properties.
Prometheus metrics for cache are not currently exposed — use middleware instance attributes for monitoring.

**Example PromQL Queries:**

```promql
# Request rate (5m average)
sum(rate(onion_requests_total[5m])) by (pipeline_name)

# P95 latency
histogram_quantile(0.95, sum(rate(onion_request_duration_seconds_bucket[5m])) by (le, pipeline_name))

# Error rate
sum(rate(onion_requests_total{status="error"}[5m])) / sum(rate(onion_requests_total[5m]))

# Token consumption rate (tokens/min)
sum(rate(onion_tokens_total[5m])) by (model) * 60
```

---

## Grafana Dashboard Setup

### Quick Start (Import JSON)

1. **Open Grafana** → Dashboards → Import
2. **Upload JSON file**: `monitoring/grafana_dashboard.json`
3. **Select Prometheus datasource**
4. **Click "Import"**

The dashboard includes:
- ✅ Request rate & error rate trends
- ✅ P95/P99 latency percentiles
- ✅ Hourly token usage breakdown
- ✅ Active requests gauge
- ✅ Error budget remaining (30-day SLO)
- ✅ Tool call success rate
- ✅ Finish reason distribution (pie chart)

### Dashboard Panels Explained

#### Panel 1: Request Rate & Error Rate
- **Purpose**: Monitor traffic volume and error spikes
- **Alert threshold**: Error rate > 5% for 5 minutes

#### Panel 2: P95/P99 Latency
- **Purpose**: Track tail latency for SLA compliance
- **SLO target**: P95 < 2s, P99 < 5s

#### Panel 3: Token Usage (Hourly)
- **Purpose**: Cost tracking and anomaly detection
- **Alert threshold**: Sudden 2x increase in token rate

#### Panel 4: Active Requests
- **Purpose**: Real-time load monitoring
- **Warning threshold**: > 50 concurrent requests
- **Critical threshold**: > 100 concurrent requests

#### Panel 5: Error Budget Remaining (30d)
- **Purpose**: SLO burn rate visualization
- **Formula**: `(1 - error_rate) * 100` over 30 days
- **SLO target**: 99.9% availability = 0.1% error budget

#### Panel 6: Tool Call Success Rate
- **Purpose**: Monitor tool execution reliability
- **SLO target**: > 95% success rate

#### Panel 7: Requests by Finish Reason
- **Purpose**: Understand response patterns (stop, length, tool_calls, etc.)

---

## Alertmanager Rules

### Pre-configured Rules

See `monitoring/alertmanager_rules.yml` for complete rule definitions.

#### Critical Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `HighErrorRate` | Error rate > 10% for 5m | Critical | Page on-call engineer |
| `HighLatencyP99` | P99 latency > 10s for 5m | Critical | Investigate provider issues |
| `LowErrorBudget` | < 50% error budget remaining | Critical | Halt deployments, investigate |

#### Warning Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `ElevatedErrorRate` | Error rate > 5% for 5m | Warning | Notify team channel |
| `HighLatencyP95` | P95 latency > 2s for 5m | Warning | Monitor closely |
| `TokenSpike` | Token rate 2x baseline | Warning | Check for abuse/anomalies |
| `ToolCallFailures` | Tool success rate < 90% | Warning | Review tool implementations |

### Example Alert Rule (YAML)

```yaml
groups:
  - name: onion_core_alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(onion_requests_total{status="error"}[5m])) 
          / 
          sum(rate(onion_requests_total[5m])) 
          > 0.10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value | humanizePercentage }} for pipeline {{ $labels.pipeline_name }}"
          runbook_url: "https://wiki.example.com/runbooks/onion-core/high-error-rate"
```

---

## SLO/SLI Definitions

### Service Level Objectives (SLOs)

| SLO Name | Target | Measurement Window |
|----------|--------|-------------------|
| **Availability** | 99.9% | 30 days |
| **Latency P95** | < 5 seconds | Rolling 5m |
| **Latency P99** | < 10 seconds | Rolling 5m |
| **Tool Call Success** | > 95% | Rolling 1h |

### Service Level Indicators (SLIs)

```promql
# Availability SLI
1 - (
  sum(increase(onion_requests_total{status="error"}[30d]))
  /
  sum(increase(onion_requests_total[30d]))
)

# Latency SLI (P95)
histogram_quantile(0.95, sum(rate(onion_request_duration_seconds_bucket[5m])) by (le))

# Tool Call Success SLI
sum(rate(onion_tool_calls_total{status="ok"}[1h]))
/
sum(rate(onion_tool_calls_total[1h]))
```

### Error Budget Calculation

For 99.9% availability SLO over 30 days:
- **Total requests**: ~2.59M (assuming 1000 req/min)
- **Allowed errors**: 2,590 (0.1%)
- **Error budget burn rate**: Track daily consumption

---

## Health Check Endpoints

Onion Core provides HTTP health check endpoints for Kubernetes probes:

### Endpoints

| Endpoint | Purpose | HTTP 200 Condition | HTTP 503 Condition |
|----------|---------|-------------------|-------------------|
| `/health` | Combined check | Pipeline healthy | Not started or degraded |
| `/health/live` | Liveness probe | Process alive | N/A (always 200) |
| `/health/ready` | Readiness probe | Ready to serve | Not ready |
| `/health/startup` | Startup probe | Startup complete | Still starting |

### Kubernetes Deployment Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: onion-core-app
spec:
  template:
    spec:
      containers:
        - name: app
          image: your-app:latest
          ports:
            - containerPort: 8080
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          startupProbe:
            httpGet:
              path: /health/startup
              port: 8080
            failureThreshold: 30
            periodSeconds: 10
```

### Python Integration Example

```python
from onion_core import Pipeline, EchoProvider, start_health_server

# Create pipeline
pipeline = Pipeline(provider=EchoProvider())

# Start health check server on port 8080
health_server = start_health_server(pipeline, host="0.0.0.0", port=8080)

# Your application logic here...

# Graceful shutdown
health_server.stop()
```

---

## Troubleshooting

### Common Issues

#### 1. No Metrics Appearing in Grafana

**Symptoms**: Dashboard shows "No data"

**Checks**:
```bash
# Verify metrics endpoint is accessible
curl http://localhost:8080/metrics

# Check Prometheus scrape targets
curl http://prometheus:9090/api/v1/targets

# Verify metric names match
grep "onion_" <(curl -s http://localhost:8080/metrics)
```

**Solutions**:
- Ensure `MetricsMiddleware` is added to pipeline
- Check Prometheus scrape interval (should be ≤ 15s)
- Verify label consistency across metrics

#### 2. High Latency Alerts

**Symptoms**: P95/P99 latency exceeds SLO

**Diagnostic Steps**:
1. Check provider-specific latency:
   ```promql
   histogram_quantile(0.95, sum(rate(onion_request_duration_seconds_bucket{model="gpt-4"}[5m])) by (le))
   ```
2. Identify slow middleware:
   - Enable debug logging: `ONION__OBSERVABILITY__LOG_LEVEL=DEBUG`
   - Check middleware timeout settings
3. Review circuit breaker status:
   ```python
   health = pipeline.health_check()
   print(health["circuit_breakers"])
   ```

**Solutions**:
- Add fallback providers for redundancy
- Tune `provider_timeout` and `max_retries`
- Enable response caching for repeated queries

#### 3. Error Budget Depleting Fast

**Symptoms**: < 50% error budget remaining with > 15 days left in window

**Investigation**:
```promql
# Daily error budget burn rate
sum(increase(onion_requests_total{status="error"}[1d]))
/
sum(increase(onion_requests_total[1d]))
```

**Actions**:
1. Identify error patterns by finish_reason
2. Check for specific model/provider failures
3. Review recent deployments for regressions
4. Consider temporarily reducing traffic to problematic providers

### Logging Best Practices

Enable structured JSON logging for easier debugging:

```python
from onion_core.observability import configure_logging

configure_logging(
    level="INFO",
    json_format=True,
    logger_name="onion_core"
)
```

**Key log fields**:
- `request_id`: Unique identifier for request tracing
- `trace_id`: Distributed trace identifier (OpenTelemetry compatible)
- `span_id`: Individual span within a trace
- `error_code`: Error code from `ErrorCode` enum (e.g., `ONI-P400`)
- `pipeline_name`: Pipeline instance name
- `duration_ms`: Operation duration

**StructuredLogAdapter**: Inject context into any logger:

```python
from onion_core.observability.logging import StructuredLogAdapter

logger = StructuredLogAdapter(
    logging.getLogger("my_module"),
    request_id="req-abc123",
    trace_id="trace-xyz",
)
logger.info("Processing started", extra={"span_id": "span-1"})
# JSON output includes: request_id, trace_id, span_id automatically
```

**RequestContext (src/ library)**: Propagate request context via `ContextVar`:

```python
from src.observability import RequestContext, current_request_id

with RequestContext(request_id="req-1", trace_id="trace-1"):
    print(current_request_id())  # "req-1"
    # All nested async calls share the same context
```

---

## Additional Resources

- [Architecture Design](../docs/architecture.md)
- [API Reference](../docs/api_reference.md)
- [Error Code Usage](../docs/error_code_usage.md)
- [Degradation Strategy](../docs/degradation_strategy.md)

---

## Support

For issues or questions:
- 📧 Email: support@example.com
- 💬 Slack: #onion-core-support
- 🐛 GitHub Issues: https://github.com/0z2w2j1/onion-core/issues
