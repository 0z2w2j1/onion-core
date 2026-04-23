# Onion Core - Monitoring & Alerting Guide

> Version: v0.6.0 | Updated: 2026-04-24

## 1. Overview

This document provides comprehensive monitoring, alerting, and SLO/SLI definitions for production deployments of Onion Core.

---

## 2. Prometheus Metrics

Onion Core exposes the following metrics via `prometheus-client`:

### 2.1 Request Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onion_requests_total` | Counter | `pipeline_name`, `model`, `finish_reason`, `status` | Total number of pipeline requests |
| `onion_request_duration_seconds` | Histogram | `pipeline_name`, `model` | Pipeline request latency (buckets: 0.1s - 30s) |
| `onion_active_requests` | Gauge | `pipeline_name` | Number of requests currently being processed |

### 2.2 Token Usage Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onion_tokens_total` | Counter | `pipeline_name`, `model`, `type` | Total tokens consumed (`type`: prompt/completion) |

### 2.3 Tool Call Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onion_tool_calls_total` | Counter | `pipeline_name`, `tool_name`, `status` | Total tool calls (`status`: ok/error/blocked) |

---

## 3. Alertmanager Rules

Save the following as `alertmanager_rules.yml` and include it in your Prometheus Alertmanager configuration:

```yaml
groups:
  - name: onion_core_alerts
    rules:
      # ── High Error Rate ────────────────────────────────────────────────
      - alert: OnionCoreHighErrorRate
        expr: |
          sum(rate(onion_requests_total{status="error"}[5m])) 
          / 
          sum(rate(onion_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
          team: ai-platform
        annotations:
          summary: "High error rate in Onion Core (>5%)"
          description: |
            Error rate is {{ $value | humanizePercentage }} over the last 5 minutes.
            Pipeline: {{ $labels.pipeline_name }}
          runbook_url: "https://wiki.internal/runbooks/onion-core-high-error-rate"

      # ── High Latency (P95) ─────────────────────────────────────────────
      - alert: OnionCoreHighLatencyP95
        expr: |
          histogram_quantile(0.95, 
            sum(rate(onion_request_duration_seconds_bucket[5m])) 
            by (le, pipeline_name, model)
          ) > 10
        for: 10m
        labels:
          severity: warning
          team: ai-platform
        annotations:
          summary: "High P95 latency in Onion Core (>10s)"
          description: |
            P95 latency is {{ $value | humanizeDuration }} for pipeline {{ $labels.pipeline_name }}, model {{ $labels.model }}.
          runbook_url: "https://wiki.internal/runbooks/onion-core-high-latency"

      # ── Circuit Breaker Open ───────────────────────────────────────────
      - alert: OnionCoreCircuitBreakerOpen
        expr: |
          # Note: This requires custom metric export from CircuitBreaker
          # For now, monitor via logs or add custom metric
          absent(onion_requests_total) == 0
        for: 1m
        labels:
          severity: warning
          team: ai-platform
        annotations:
          summary: "Potential circuit breaker activation"
          description: |
            No requests observed in the last minute. Check if circuit breaker is open.
            Investigate provider health and fallback chains.

      # ── Token Budget Exceeded ──────────────────────────────────────────
      - alert: OnionCoreTokenBudgetExceeded
        expr: |
          sum(increase(onion_tokens_total{type="completion"}[1h])) > 1000000
        for: 0m
        labels:
          severity: warning
          team: ai-platform
        annotations:
          summary: "Hourly token budget exceeded (>1M tokens)"
          description: |
            Consumed {{ $value | humanize }} completion tokens in the last hour.
            Review usage patterns and consider rate limiting.

      # ── Tool Call Failure Rate ─────────────────────────────────────────
      - alert: OnionCoreToolCallFailureRate
        expr: |
          sum(rate(onion_tool_calls_total{status="error"}[5m])) 
          / 
          sum(rate(onion_tool_calls_total[5m])) > 0.1
        for: 5m
        labels:
          severity: warning
          team: ai-platform
        annotations:
          summary: "High tool call failure rate (>10%)"
          description: |
            Tool call error rate is {{ $value | humanizePercentage }}.
            Check tool implementations and external dependencies.

      # ── No Active Requests (Potential Outage) ──────────────────────────
      - alert: OnionCoreNoActiveRequests
        expr: |
          sum(onion_active_requests) == 0
          and
          sum(increase(onion_requests_total[15m])) > 100
        for: 5m
        labels:
          severity: critical
          team: ai-platform
        annotations:
          summary: "No active requests despite recent traffic"
          description: |
            System received {{ $value }} requests in the last 15 minutes but has 0 active requests.
            Possible service outage or deployment issue.
```

---

## 4. Grafana Dashboard

Import the following JSON into Grafana to visualize Onion Core metrics:

```json
{
  "dashboard": {
    "title": "Onion Core - Production Monitoring",
    "tags": ["onion-core", "llm", "agent"],
    "timezone": "browser",
    "panels": [
      {
        "title": "Request Rate & Error Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(onion_requests_total[5m])) by (pipeline_name)",
            "legendFormat": "{{pipeline_name}} - Total"
          },
          {
            "expr": "sum(rate(onion_requests_total{status=\"error\"}[5m])) by (pipeline_name)",
            "legendFormat": "{{pipeline_name}} - Errors"
          }
        ],
        "yaxes": [{"label": "req/s"}, {"label": ""}]
      },
      {
        "title": "P95/P99 Latency",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(onion_request_duration_seconds_bucket[5m])) by (le, pipeline_name))",
            "legendFormat": "{{pipeline_name}} - P95"
          },
          {
            "expr": "histogram_quantile(0.99, sum(rate(onion_request_duration_seconds_bucket[5m])) by (le, pipeline_name))",
            "legendFormat": "{{pipeline_name}} - P99"
          }
        ],
        "yaxes": [{"label": "seconds"}, {"label": ""}]
      },
      {
        "title": "Token Usage (Hourly)",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(increase(onion_tokens_total{type=\"prompt\"}[1h])) by (model)",
            "legendFormat": "{{model}} - Prompt Tokens"
          },
          {
            "expr": "sum(increase(onion_tokens_total{type=\"completion\"}[1h])) by (model)",
            "legendFormat": "{{model}} - Completion Tokens"
          }
        ],
        "yaxes": [{"label": "tokens/hour"}, {"label": ""}]
      },
      {
        "title": "Active Requests",
        "type": "singlestat",
        "targets": [
          {
            "expr": "sum(onion_active_requests)",
            "legendFormat": "Active"
          }
        ],
        "thresholds": "50,100",
        "colorValue": true
      },
      {
        "title": "Tool Call Success Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(onion_tool_calls_total{status=\"ok\"}[5m])) / sum(rate(onion_tool_calls_total[5m]))",
            "legendFormat": "Success Rate"
          }
        ],
        "yaxes": [{"label": "rate", "min": 0, "max": 1}, {"label": ""}]
      }
    ],
    "time": {"from": "now-6h", "to": "now"},
    "refresh": "30s"
  }
}
```

---

## 5. SLO/SLI Definitions

### 5.1 Service Level Indicators (SLIs)

| SLI | Measurement | Target |
|-----|-------------|--------|
| **Availability** | `(successful_requests / total_requests) × 100` | ≥ 99.9% |
| **Latency (P95)** | 95th percentile of `onion_request_duration_seconds` | ≤ 5s |
| **Latency (P99)** | 99th percentile of `onion_request_duration_seconds` | ≤ 10s |
| **Token Efficiency** | `(completion_tokens / prompt_tokens)` ratio | ≤ 3.0 |
| **Tool Call Success** | `(successful_tool_calls / total_tool_calls) × 100` | ≥ 95% |

### 5.2 Service Level Objectives (SLOs)

#### SLO-1: Request Availability
- **Objective**: 99.9% of requests complete successfully (status != "error")
- **Window**: 30-day rolling window
- **Error Budget**: 0.1% = ~43 minutes of downtime per month
- **Alert Threshold**: Error rate > 5% for 5 minutes

#### SLO-2: Response Latency
- **Objective**: 95% of requests complete within 5 seconds
- **Window**: 7-day rolling window
- **Measurement**: `histogram_quantile(0.95, onion_request_duration_seconds)`
- **Alert Threshold**: P95 > 10s for 10 minutes

#### SLO-3: Token Budget
- **Objective**: Stay within monthly token budget
- **Budget**: Configurable per deployment (default: 10M tokens/month)
- **Alert Threshold**: 80% of budget consumed with 7+ days remaining

#### SLO-4: Tool Reliability
- **Objective**: 95% of tool calls execute successfully
- **Window**: 24-hour rolling window
- **Measurement**: `onion_tool_calls_total{status="ok"} / onion_tool_calls_total`
- **Alert Threshold**: Failure rate > 10% for 5 minutes

### 5.3 Error Budget Policy

| Burn Rate | Action | Timeline |
|-----------|--------|----------|
| **1×** (normal) | Monitor trends | Weekly review |
| **2×** | Investigate root cause | Within 24 hours |
| **5×** | Engage on-call engineer | Immediate response |
| **10×** | Freeze non-critical deployments | Until stabilized |
| **14×** | Incident declared, all-hands | Escalate to leadership |

**Calculation**: `Burn Rate = Actual Error Rate / Allowed Error Rate`

Example: If allowed error rate is 0.1% and actual is 1%, burn rate = 10×

---

## 6. Production Deployment Checklist

### 6.1 Pre-Deployment

- [ ] Configure Prometheus scraping endpoint (`/metrics`)
- [ ] Import Alertmanager rules
- [ ] Import Grafana dashboard
- [ ] Set up PagerDuty/OpsGenie integration for critical alerts
- [ ] Define token budgets per environment (dev/staging/prod)
- [ ] Configure rate limits based on expected QPS

### 6.2 Post-Deployment

- [ ] Verify metrics are being scraped (check Prometheus targets)
- [ ] Confirm alerts fire correctly (test with synthetic errors)
- [ ] Validate Grafana dashboard displays data
- [ ] Set up weekly SLO review meetings
- [ ] Document runbooks for common alert scenarios

### 6.3 Ongoing Operations

- [ ] Review error budget burn rate weekly
- [ ] Adjust alert thresholds based on historical data
- [ ] Update dashboards as new features are added
- [ ] Conduct quarterly SLO retrospectives

---

## 7. Troubleshooting Common Alerts

### High Error Rate

**Symptoms**: `OnionCoreHighErrorRate` alert fires

**Investigation Steps**:
1. Check provider health status (OpenAI/Anthropic/etc.)
2. Review fallback provider chain activation
3. Inspect circuit breaker state logs
4. Verify API keys and network connectivity

**Common Causes**:
- Upstream provider outage
- Invalid API credentials
- Rate limiting by provider
- Network issues

### High Latency

**Symptoms**: `OnionCoreHighLatencyP95` alert fires

**Investigation Steps**:
1. Check provider response times
2. Review middleware processing overhead
3. Inspect context window size (large contexts = slower)
4. Verify network latency to provider endpoints

**Optimization Tips**:
- Enable context truncation (`ContextWindowMiddleware`)
- Use streaming for long responses
- Implement caching for repeated queries
- Consider faster models for latency-sensitive use cases

### Circuit Breaker Activation

**Symptoms**: Multiple fallback providers activated, reduced throughput

**Investigation Steps**:
1. Check which provider triggered the circuit breaker
2. Review failure patterns (timeouts vs. errors)
3. Verify recovery timeout settings
4. Monitor HALF_OPEN state transitions

**Recovery Actions**:
- Wait for automatic recovery (default: 30s)
- Manually reset circuit breaker if needed
- Scale up fallback provider capacity
- Investigate root cause of failures

---

## 8. Custom Metrics Extension

To add custom metrics, extend the `MetricsMiddleware`:

```python
from onion_core.observability.metrics import MetricsMiddleware
from prometheus_client import Counter

class CustomMetricsMiddleware(MetricsMiddleware):
    def __init__(self, pipeline_name: str = "default"):
        super().__init__(pipeline_name)
        self._custom_metric = Counter(
            "onion_custom_events_total",
            "Custom business events",
            ["event_type"]
        )
    
    async def process_response(self, context, response):
        # Record custom metric
        if response.content and len(response.content) > 1000:
            self._custom_metric.labels(event_type="long_response").inc()
        return await super().process_response(context, response)
```

---

## 9. References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Grafana Dashboard JSON Model](https://grafana.com/docs/grafana/latest/dashboards/json-model/)
- [SRE Book - Error Budgets](https://sre.google/sre-book/service-level-objectives/)

---

# Onion Core - 监控与告警指南

> 版本：v0.6.0 | 更新日期：2026-04-24

## 1. 概述

本文档提供 Onion Core 生产部署的全面监控、告警和 SLO/SLI 定义。

## 2. Prometheus 指标

Onion Core 通过 `prometheus-client` 暴露以下指标（详见英文版第 2 节）。

## 3. Alertmanager 告警规则

告警规则配置见英文版第 3 节 `alertmanager_rules.yml`。

## 4. Grafana 仪表板

Grafana 仪表板 JSON 配置见英文版第 4 节。

## 5. SLO/SLI 定义

### 5.1 服务等级指标 (SLI)

| SLI | 测量方式 | 目标 |
|-----|---------|------|
| **可用性** | `(成功请求数 / 总请求数) × 100` | ≥ 99.9% |
| **延迟 (P95)** | `onion_request_duration_seconds` 的 95 百分位 | ≤ 5秒 |
| **延迟 (P99)** | `onion_request_duration_seconds` 的 99 百分位 | ≤ 10秒 |
| **Token 效率** | `completion_tokens / prompt_tokens` 比率 | ≤ 3.0 |
| **工具调用成功率** | `(成功工具调用数 / 总工具调用数) × 100` | ≥ 95% |

### 5.2 服务等级目标 (SLO)

详见英文版第 5.2 节，包含四个核心 SLO：
- SLO-1: 请求可用性 (99.9%)
- SLO-2: 响应延迟 (P95 ≤ 5s)
- SLO-3: Token 预算控制
- SLO-4: 工具可靠性 (≥ 95%)

### 5.3 错误预算策略

| 消耗速率 | 行动 | 时间线 |
|---------|------|--------|
| **1×** (正常) | 监控趋势 | 每周审查 |
| **2×** | 调查根本原因 | 24小时内 |
| **5×** | 联系值班工程师 | 立即响应 |
| **10×** | 冻结非关键部署 | 直到稳定 |
| **14×** | 声明事故，全员参与 | 上报领导层 |

---

## 6. 生产部署检查清单

详见英文版第 6 节，包括部署前、部署后和持续运营的检查项。

## 7. 常见告警故障排除

详见英文版第 7 节，涵盖高错误率、高延迟和熔断器激活的诊断步骤。

## 8. 自定义指标扩展

扩展 `MetricsMiddleware` 添加自定义指标的方法见英文版第 8 节。

## 9. 参考资料

- [Prometheus 文档](https://prometheus.io/docs/)
- [Alertmanager 配置](https://prometheus.io/docs/alerting/latest/configuration/)
- [Grafana 仪表板](https://grafana.com/docs/grafana/latest/dashboards/json-model/)
- [SRE 书籍 - 错误预算](https://sre.google/sre-book/service-level-objectives/)
