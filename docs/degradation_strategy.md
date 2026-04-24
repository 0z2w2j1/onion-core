# Onion Core - Degradation Strategy Document

> Version: v0.7.0 | Updated: 2026-04-24

## 1. Overview

Degradation Strategy defines how the system gracefully degrades service quality when the primary chain fails or becomes unavailable. Onion Core uses **multi-layer degradation**:

```
Request → [Middleware Chain] → Primary Provider → Failed?
                                      ├─ Retry (exponential backoff)
                                      ├─ Circuit breaker check → skip
                                      ├─ Fallback Provider 1 → Failed?
                                      │                       ├─ Fallback Provider 2 → ...
                                      └─ All failed → Throw FallbackExhausted error
```

---

## 2. Error Classification & Handling Strategy

All exceptions are classified into three categories via `RetryPolicy.classify()`:

| Classification | Code Value | Meaning | Handling |
|------|--------|------|----------|
| `RETRY` | `retry` | Transient failure (network timeout, connection error) | Exponential backoff retry on current Provider |
| `FALLBACK` | `fallback` | Service layer error (rate limit, Provider temporarily unavailable) | Skip current Provider, try next Fallback |
| `FATAL` | `fatal` | Fatal error (security block, parameter error, quota exhausted) | Throw immediately, no retry, no Fallback |

### 2.1 Error Code & Strategy Mapping

| Error Code | Name | Classification | Description |
|-----------|------|------|------|
| `ONI-S100` | SECURITY_BLOCKED_KEYWORD | FATAL | Request contains blocked keyword |
| `ONI-S101` | SECURITY_PII_DETECTED | FATAL | Personally identifiable information detected |
| `ONI-S102` | SECURITY_PROMPT_INJECTION | FATAL | Prompt injection attack detected |
| `ONI-S103` | SECURITY_FORBIDDEN_TOOL | FATAL | Tool call prohibited by security policy |
| `ONI-R200` | RATE_LIMIT_EXCEEDED | FALLBACK | API rate limit triggered |
| `ONI-R201` | RATE_LIMIT_WINDOW_FULL | FALLBACK | Rate limit window full |
| `ONI-C300` | CIRCUIT_OPEN | FALLBACK | Circuit breaker open, skip this Provider |
| `ONI-C301` | CIRCUIT_TRIPPED | FALLBACK | Circuit breaker tripped due to consecutive failures |
| `ONI-P400` | PROVIDER_AUTH_FAILED | FATAL | API Key invalid or expired |
| `ONI-P401` | PROVIDER_QUOTA_EXCEEDED | FATAL | Account quota exhausted |
| `ONI-P402` | PROVIDER_MODEL_NOT_FOUND | FATAL | Requested model does not exist |
| `ONI-P403` | PROVIDER_CONTENT_FILTER | FATAL | Content blocked by Provider security policy |
| `ONI-P404` | PROVIDER_CONTEXT_OVERFLOW | FATAL | Exceeds context window |
| `ONI-P405` | PROVIDER_INVALID_REQUEST | FATAL | Request parameter format error |
| `ONI-T700` | TIMEOUT_PROVIDER | RETRY | Provider API call timeout |
| `ONI-T701` | TIMEOUT_MIDDLEWARE | RETRY | Middleware execution timeout |
| `ONI-F800` | FALLBACK_TRIGGERED | FALLBACK | Degradation triggered, switching Provider |
| `ONI-F801` | FALLBACK_EXHAUSTED | FATAL | All Providers failed |
| `ONI-F802` | FALLBACK_PROVIDER_FAILED | FALLBACK | Fallback Provider call failed |

---

## 3. Retry Mechanism

### 3.1 Exponential Backoff Algorithm

```
delay = base_delay × 2^attempt + random_jitter(0, 0.1)

Default parameters:
  max_retries      = 0 (default, configured by user)
  retry_base_delay = 0.5 seconds
  jitter           = [0, 0.1) seconds random jitter
```

### 3.2 Retry Scope

Retry only applies to `RETRY` exceptions (transient failures). The following are **NOT retried**:

- `FATAL` exceptions (security block, parameter errors, etc.)
- `FALLBACK` exceptions (rate limit, circuit breaker) — skip directly to Provider

### 3.3 Configuration Example

```python
pipeline = Pipeline(
    provider=primary_provider,
    max_retries=3,              # Max 3 retries
    retry_base_delay=0.5,       # Base delay 0.5s
    provider_timeout=30.0,      # Provider call timeout 30s
)
```

---

## 4. Circuit Breaker Mechanism

### 4.1 State Machine

```
         Consecutive failures ≥ threshold
    ┌──────────────────────────┐
    │                          ▼
  [CLOSED] ────────────────► [OPEN]
    ▲                          │
    │                          │ After recovery_timeout
    │  Success ≥ success_threshold in half-open │
    │                          ▼
    └────────── [HALF_OPEN] ◄──┘
                │
                │ 1 failure in half-open
                ▼
             [OPEN]
```

### 4.2 Circuit Breaker Parameters

| Parameter | Default Value | Description |
|------|--------|------|
| `failure_threshold` | 5 | How many consecutive failures trigger circuit break |
| `recovery_timeout` | 30.0 seconds | How long OPEN state persists before entering HALF_OPEN |
| `success_threshold` | 2 | How many consecutive successes in HALF_OPEN to restore CLOSED |

### 4.3 Relationship Between Circuit Breaker and Degradation

Circuit breaker is **preventive degradation**: when a Provider consecutively fails, temporarily skip it to avoid wasting resources on invalid requests.

```
Provider A circuit broken → Pipeline automatically skips A → Try Fallback Provider B
```

---

## 5. Fallback Provider Chain

### 5.1 Configuration

```python
pipeline = Pipeline(
    provider=openai_provider,          # Primary Provider
    fallback_providers=[
        anthropic_provider,            # First fallback
        local_ollama_provider,         # Second fallback
    ],
)
```

### 5.2 Execution Order

1. Try primary Provider
2. If `FALLBACK` or retries exhausted, switch to Fallback Provider 1
3. Try all Fallback Providers in order
4. All failed → throw `ONI-F801 FALLBACK_EXHAUSTED`

### 5.3 Circuit Breaker & Fallback Coordination

Each Provider (including Fallback) has its own circuit breaker:

```
Primary Provider → Circuit broken → Skip → Fallback 1 → Circuit broken → Skip → Fallback 2 → ...
```

---

## 6. Middleware Fault Isolation

### 6.1 Non-mandatory Middleware

Default `is_mandatory = False`, execution failure is **isolated** instead of breaking the chain:

```python
# Non-mandatory middleware failure: log and continue
try:
    result = await mw.process_request(context)
except Exception:
    log_error()
    continue  # Don't break chain
```

### 6.2 Mandatory Middleware

Setting `is_mandatory = True` makes failure **break the entire chain**:

```python
class CriticalSecurityMiddleware(BaseMiddleware):
    is_mandatory = True  # Security middleware must succeed or break chain
    priority = 200
```

### 6.3 Middleware Timeout

Individual middleware can set independent timeout via `timeout` attribute (overrides global config):

```python
class MyMiddleware(BaseMiddleware):
    timeout = 5.0  # This middleware executes max 5 seconds
```

---

## 7. Degradation Strategy Configuration Suggestions

### 7.1 Production Environment Recommended Config

```python
cfg = OnionConfig(
    pipeline=PipelineConfig(
        max_retries=3,
        retry_base_delay=0.5,
        provider_timeout=30.0,
        middleware_timeout=10.0,
        enable_circuit_breaker=True,
        circuit_failure_threshold=5,
        circuit_recovery_timeout=30.0,
    ),
    safety=SafetyConfig(
        blocked_keywords=["ignore previous", "you are now"],
        enable_pii_masking=True,
    ),
    context_window=ContextWindowConfig(
        max_tokens=128000,
        keep_rounds=10,
    ),
)

pipeline = Pipeline.from_config(
    provider=openai_provider,
    config=cfg,
)
# Add Fallback Providers
pipeline._fallback_providers = [anthropic_provider, local_provider]
```

### 7.2 Strategy Selection for Different Scenarios

| Scenario | Recommended Strategy |
|------|----------|
| High availability API service | 3 retries + 2 Fallback Providers + circuit breaker |
| Cost-sensitive scenario | Use cheap model as primary, high-quality model as fallback |
| Data-sensitive scenario | Enable PII masking + forbid external Fallback, use only local model |
| Low latency scenario | Reduce retries, prefer local/Fallback models |

---

## 8. Error Monitoring & Alert Suggestions

### 8.1 Key Metrics

| Metric | Description | Alert Threshold Suggestion |
|------|------|--------------|
| `onion_provider_calls_total` | Total Provider calls | - |
| `onion_provider_errors_total` | Total Provider errors | Error rate > 5% |
| `onion_circuit_breaker_state` | Circuit breaker state | In OPEN state |
| `onion_fallback_calls_total` | Fallback trigger count | Frequent triggers (>10/min) |
| `onion_security_blocks_total` | Security block count | Abnormal spike |

### 8.2 Structured Log Fields

Every error should include the following fields for search and alerting:

```python
{
    "request_id": "abc123",
    "error_code": "ONI-P400",
    "error_category": "P",
    "message": "[ONI-P400] Provider authentication failed",
    "retry_outcome": "fatal",
    "provider": "OpenAIProvider",
    "timestamp": "2026-04-23T10:00:00Z",
}
```

---

## 9. Degradation Strategy Decision Tree

```
Request enters
  │
  ▼
[Middleware Chain - Security Block]
  │
  ├─ Security block → FATAL → Return error (no degradation)
  │
  ▼
[Primary Provider Call]
  │
  ├─ Success → Return result
  │
  ├─ Transient failure (RETRY)
  │    ├─ Not at max_retries → Exponential backoff retry
  │    └─ At max_retries → Switch to Fallback
  │
  ├─ Rate limit/service unavailable (FALLBACK) → Switch to Fallback
  │
  ├─ Circuit break (CIRCUIT_OPEN) → Skip → Switch to Fallback
  │
  ▼
[Fallback Provider 1]
  │
  ├─ Success → Return result
  ├─ Fail → Switch to Fallback Provider 2
  │
  ▼
[All Fallback Failed]
  │
  ▼
Throw ONI-F801 FALLBACK_EXHAUSTED (final failure)
```

---

## 10. Version History

| Version | Date | Change Content |
|------|------|----------|
| v0.7.0 | 2026-04-24 | Added ResponseCacheMiddleware, enhanced sync API, load testing suite |
| v0.6.0 | 2026-04-24 | Initial version, defined error codes and degradation strategy |

---

# Onion Core - 降级策略文档

> 版本：v0.7.0 | 更新日期：2026-04-24

## 1. 概述

降级策略（Degradation Strategy）定义了当主链路失败或不可用时，系统如何优雅地降低服务质量而非直接失败。Onion Core 采用 **多层降级** 设计：

```
请求 → [中间件链] → 主 Provider → 失败？
                                      ├─ 重试（指数退避）
                                      ├─ 熔断检测 → 跳过
                                      ├─ Fallback Provider 1 → 失败？
                                      │                       ├─ Fallback Provider 2 → ...
                                      └─ 全部失败 → 抛出 FallbackExhausted 错误
```

---

## 2. 错误分类与处置策略

所有异常通过 `RetryPolicy.classify()` 分为三类：

| 分类 | 代码值 | 含义 | 处置方式 |
|------|--------|------|----------|
| `RETRY` | `retry` | 瞬时故障（网络超时、连接错误） | 指数退避重试当前 Provider |
| `FALLBACK` | `fallback` | 服务层错误（限流、Provider 临时不可用） | 跳过当前 Provider，尝试下一个 Fallback |
| `FATAL` | `fatal` | 致命错误（安全拦截、参数错误、配额耗尽） | 立即抛出，不重试，不 Fallback |

### 2.1 错误码与策略映射表

| 错误码 | 名称 | 分类 | 说明 |
|--------|------|------|------|
| `ONI-S100` | SECURITY_BLOCKED_KEYWORD | FATAL | 请求含违禁关键词 |
| `ONI-S101` | SECURITY_PII_DETECTED | FATAL | 检测到个人敏感信息 |
| `ONI-S102` | SECURITY_PROMPT_INJECTION | FATAL | 检测到提示词注入攻击 |
| `ONI-S103` | SECURITY_FORBIDDEN_TOOL | FATAL | 工具调用被安全策略禁止 |
| `ONI-R200` | RATE_LIMIT_EXCEEDED | FALLBACK | API 限流触发 |
| `ONI-R201` | RATE_LIMIT_WINDOW_FULL | FALLBACK | 限流窗口已满 |
| `ONI-C300` | CIRCUIT_OPEN | FALLBACK | 熔断器打开，跳过该 Provider |
| `ONI-C301` | CIRCUIT_TRIPPED | FALLBACK | 熔断器因连续失败触发 |
| `ONI-P400` | PROVIDER_AUTH_FAILED | FATAL | API Key 无效或过期 |
| `ONI-P401` | PROVIDER_QUOTA_EXCEEDED | FATAL | 账户配额耗尽 |
| `ONI-P402` | PROVIDER_MODEL_NOT_FOUND | FATAL | 请求的模型不存在 |
| `ONI-P403` | PROVIDER_CONTENT_FILTER | FATAL | 内容被 Provider 安全策略拦截 |
| `ONI-P404` | PROVIDER_CONTEXT_OVERFLOW | FATAL | 超出上下文窗口 |
| `ONI-P405` | PROVIDER_INVALID_REQUEST | FATAL | 请求参数格式错误 |
| `ONI-T700` | TIMEOUT_PROVIDER | RETRY | Provider API 调用超时 |
| `ONI-T701` | TIMEOUT_MIDDLEWARE | RETRY | 中间件执行超时 |
| `ONI-F800` | FALLBACK_TRIGGERED | FALLBACK | 已触发降级，切换 Provider |
| `ONI-F801` | FALLBACK_EXHAUSTED | FATAL | 所有 Provider 均失败 |
| `ONI-F802` | FALLBACK_PROVIDER_FAILED | FALLBACK | Fallback Provider 调用失败 |

---

## 3. 重试机制

### 3.1 指数退避算法

```
delay = base_delay × 2^attempt + random_jitter(0, 0.1)

默认参数：
  max_retries      = 0（默认不重试，由用户配置）
  retry_base_delay = 0.5 秒
  jitter           = [0, 0.1) 秒随机抖动
```

### 3.2 重试范围

重试仅适用于 `RETRY` 类异常（瞬时故障）。以下情况**不重试**：

- `FATAL` 类异常（安全拦截、参数错误等）
- `FALLBACK` 类异常（限流、熔断）— 直接切换 Provider

### 3.3 配置示例

```python
pipeline = Pipeline(
    provider=primary_provider,
    max_retries=3,              # 最多重试 3 次
    retry_base_delay=0.5,       # 基础延迟 0.5s
    provider_timeout=30.0,      # Provider 调用超时 30s
)
```

---

## 4. 熔断机制

### 4.1 状态机

```
         连续失败 ≥ threshold
    ┌──────────────────────────┐
    │                          ▼
  [CLOSED] ────────────────► [OPEN]
    ▲                          │
    │                          │ 经过 recovery_timeout
    │  半开期成功 ≥ success_threshold  │
    │                          ▼
    └────────── [HALF_OPEN] ◄──┘
                │
                │ 半开期失败 1 次
                ▼
             [OPEN]
```

### 4.2 熔断参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `failure_threshold` | 5 | 连续失败多少次触发熔断 |
| `recovery_timeout` | 30.0 秒 | OPEN 状态持续多久后进入 HALF_OPEN |
| `success_threshold` | 2 | HALF_OPEN 状态下连续成功多少次恢复 CLOSED |

### 4.3 熔断与降级的关系

熔断是**预防性降级**：当某个 Provider 连续失败时，暂时跳过它，避免无效请求浪费资源。

```
Provider A 熔断 → Pipeline 自动跳过 A → 尝试 Fallback Provider B
```

---

## 5. Fallback Provider 链

### 5.1 配置方式

```python
pipeline = Pipeline(
    provider=openai_provider,          # 主 Provider
    fallback_providers=[
        anthropic_provider,            # 第一备用
        local_ollama_provider,         # 第二备用
    ],
)
```

### 5.2 执行顺序

1. 主 Provider 尝试调用
2. 若触发 `FALLBACK` 或重试耗尽，切换到 Fallback Provider 1
3. 依次尝试所有 Fallback Provider
4. 全部失败 → 抛出 `ONI-F801 FALLBACK_EXHAUSTED`

### 5.3 熔断与 Fallback 的协同

每个 Provider（包括 Fallback）都有独立的熔断器：

```
主 Provider → 熔断 → 跳过 → Fallback 1 → 熔断 → 跳过 → Fallback 2 → ...
```

---

## 6. 中间件故障隔离

### 6.1 非强制中间件

默认 `is_mandatory = False`，执行失败会被**隔离**而非中断链路：

```python
# 非强制中间件失败：记录日志，继续后续中间件
try:
    result = await mw.process_request(context)
except Exception:
    log_error()
    continue  # 不中断链路
```

### 6.2 强制中间件

设置 `is_mandatory = True` 后，失败将**中断整个链路**：

```python
class CriticalSecurityMiddleware(BaseMiddleware):
    is_mandatory = True  # 安全中间件必须成功，否则中断
    priority = 200
```

### 6.3 中间件超时

单个中间件可通过 `timeout` 属性设置独立超时（覆盖全局配置）：

```python
class MyMiddleware(BaseMiddleware):
    timeout = 5.0  # 该中间件最多执行 5 秒
```

---

## 7. 降级策略配置建议

### 7.1 生产环境推荐配置

```python
cfg = OnionConfig(
    pipeline=PipelineConfig(
        max_retries=3,
        retry_base_delay=0.5,
        provider_timeout=30.0,
        middleware_timeout=10.0,
        enable_circuit_breaker=True,
        circuit_failure_threshold=5,
        circuit_recovery_timeout=30.0,
    ),
    safety=SafetyConfig(
        blocked_keywords=["ignore previous", "you are now"],
        enable_pii_masking=True,
    ),
    context_window=ContextWindowConfig(
        max_tokens=128000,
        keep_rounds=10,
    ),
)

pipeline = Pipeline.from_config(
    provider=openai_provider,
    config=cfg,
)
# 添加 Fallback Provider
pipeline._fallback_providers = [anthropic_provider, local_provider]
```

### 7.2 不同场景的策略选择

| 场景 | 推荐策略 |
|------|----------|
| 高可用 API 服务 | 3 次重试 + 2 个 Fallback Provider + 熔断 |
| 成本敏感场景 | 主用廉价模型，Fallback 用高质量模型 |
| 数据敏感场景 | 启用 PII 脱敏 + 禁止外部 Fallback，仅用本地模型 |
| 低延迟场景 | 减少重试次数，优先本地/Fallback 模型 |

---

## 8. 错误监控与告警建议

### 8.1 关键指标

| 指标 | 说明 | 告警阈值建议 |
|------|------|--------------|
| `onion_provider_calls_total` | Provider 调用总量 | - |
| `onion_provider_errors_total` | Provider 错误量 | 错误率 > 5% |
| `onion_circuit_breaker_state` | 熔断器状态 | 处于 OPEN 状态 |
| `onion_fallback_calls_total` | Fallback 触发次数 | 频繁触发（>10 次/分钟） |
| `onion_security_blocks_total` | 安全拦截次数 | 异常激增 |

### 8.2 日志结构化字段

每次错误都应包含以下字段，便于检索和告警：

```python
{
    "request_id": "abc123",
    "error_code": "ONI-P400",
    "error_category": "P",
    "message": "[ONI-P400] Provider authentication failed",
    "retry_outcome": "fatal",
    "provider": "OpenAIProvider",
    "timestamp": "2026-04-23T10:00:00Z",
}
```

---

## 9. 降级策略决策树

```
请求进入
  │
  ▼
[中间件链 - 安全拦截]
  │
  ├─ 安全拦截 → FATAL → 返回错误（不降级）
  │
  ▼
[主 Provider 调用]
  │
  ├─ 成功 → 返回结果
  │
  ├─ 瞬时故障 (RETRY)
  │    ├─ 未达 max_retries → 指数退避重试
  │    └─ 达 max_retries → 转 Fallback
  │
  ├─ 限流/服务不可用 (FALLBACK) → 转 Fallback
  │
  ├─ 熔断 (CIRCUIT_OPEN) → 跳过 → 转 Fallback
  │
  ▼
[Fallback Provider 1]
  │
  ├─ 成功 → 返回结果
  ├─ 失败 → 转 Fallback Provider 2
  │
  ▼
[全部 Fallback 失败]
  │
  ▼
抛出 ONI-F801 FALLBACK_EXHAUSTED（最终失败）
```

---

## 10. 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v0.6.0 | 2026-04-24 | 初始版本，定义错误码与降级策略 |
