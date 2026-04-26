# 错误码系统设计

本文解释 Onion Core 的统一错误码系统设计理念、分类原则和使用方法。

## 为什么需要统一错误码？

在没有统一错误码的系统中，错误处理面临以下问题：

### ❌ 问题 1：错误信息不一致

```python
# 不同模块返回不同格式的错误
raise Exception("API key invalid")
raise ValueError("Authentication failed")
raise RuntimeError("Invalid credentials")
```

客户端难以解析和分类这些错误。

---

### ❌ 问题 2：重试策略不明确

```python
try:
    response = await provider.complete(ctx)
except Exception as e:
    # 不知道是否应该重试
    if "timeout" in str(e):
        retry()
    elif "quota" in str(e):
        switch_provider()
    else:
        raise
```

基于字符串匹配的重试逻辑脆弱且不可靠。

---

### ❌ 问题 3：监控和告警困难

```python
# 日志中混杂各种错误信息
logger.error("Request failed: timeout")
logger.error("Request failed: auth error")
logger.error("Request failed: rate limit")

# 无法快速统计某类错误的频率
```

---

### ✅ 解决方案：统一错误码

```python
# 所有错误都有明确的 ErrorCode
raise ProviderError(error_code=ErrorCode.PROVIDER_AUTH_FAILED)
raise RateLimitExceeded(error_code=ErrorCode.RATE_LIMIT_EXCEEDED)
raise SecurityException(error_code=ErrorCode.SECURITY_PROMPT_INJECTION)
```

**优势**：
1. **结构化**：每个错误有唯一标识符
2. **可检索**：日志中可以直接搜索 `ONI-P400`
3. **自动化**：根据错误码自动选择重试策略
4. **可观测**：轻松统计各类错误的频率

---

## 错误码设计原则

### 1. 语义化命名

错误码格式：`ONI-<类别><编号>`

```
ONI-S100  → Onion Core - Security - 第 100 号错误
ONI-P401  → Onion Core - Provider - 第 401 号错误
```

**类别代码**：
- `S` - Security（安全拦截）
- `R` - Rate Limit（限流）
- `C` - Circuit Breaker（熔断）
- `P` - Provider（LLM 调用失败）
- `M` - Middleware（中间件执行错误）
- `V` - Validation（参数/配置校验）
- `T` - Timeout（超时）
- `F` - Fallback（降级/备用策略）
- `I` - Internal（内部错误）

---

### 2. 范围划分

| 错误码范围 | 类别 | 示例 |
|-----------|------|------|
| 100-199 | Security | `ONI-S100`: 关键词拦截 |
| 200-299 | Rate Limit | `ONI-R200`: 超出速率限制 |
| 300-399 | Circuit Breaker | `ONI-C300`: 熔断器开启 |
| 400-499 | Provider | `ONI-P400`: 认证失败 |
| 500-599 | Middleware | `ONI-M500`: 请求处理失败 |
| 600-699 | Validation | `ONI-V600`: 配置无效 |
| 700-799 | Timeout | `ONI-T700`: Provider 超时 |
| 800-899 | Fallback | `ONI-F800`: 触发降级 |
| 900-999 | Internal | `ONI-I900`: 未预期异常 |

**好处**：
- 通过错误码即可判断错误类型
- 便于按类别统计和告警
- 预留扩展空间（每类最多 100 个错误码）

---

### 3. 默认消息映射

每个错误码对应一个人类可读的默认消息：

```python
ERROR_MESSAGES = {
    ErrorCode.SECURITY_BLOCKED_KEYWORD: 
        "Request blocked: blocked keyword detected in input",
    
    ErrorCode.PROVIDER_AUTH_FAILED: 
        "Provider authentication failed: invalid API key or token",
    
    ErrorCode.TIMEOUT_PROVIDER: 
        "Provider API call timed out",
}
```

**使用方式**：
```python
error = OnionErrorWithCode(
    error_code=ErrorCode.PROVIDER_AUTH_FAILED,
    message="Custom message"  # 可选，覆盖默认消息
)

print(error.error_code)   # ONI-P400
print(str(error))         # Custom message（或默认消息）
```

---

## 重试策略系统

### 三种重试结果

Pipeline 根据错误码自动决定如何处理：

| 重试结果 | 行为 | 适用场景 |
|---------|------|---------|
| **RETRY** | 指数退避重试 | 瞬时故障（网络抖动、临时限流） |
| **FALLBACK** | 切换到备用 Provider | 服务不可用（熔断器开启、配额耗尽） |
| **FATAL** | 立即抛出，不重试 | 不可恢复错误（认证失败、参数错误） |

---

### 错误码到重试策略的映射

```python
_ERROR_RETRY_STR = {
    # Security → FATAL（安全拦截不应重试）
    ErrorCode.SECURITY_BLOCKED_KEYWORD: "fatal",
    ErrorCode.SECURITY_PII_DETECTED: "fatal",
    ErrorCode.SECURITY_PROMPT_INJECTION: "fatal",
    
    # Rate Limit → FALLBACK（可尝试备用 Provider）
    ErrorCode.RATE_LIMIT_EXCEEDED: "fallback",
    ErrorCode.RATE_LIMIT_WINDOW_FULL: "fallback",
    
    # Circuit Breaker → FALLBACK（跳过当前 Provider）
    ErrorCode.CIRCUIT_OPEN: "fallback",
    ErrorCode.CIRCUIT_TRIPPED: "fallback",
    
    # Provider → 区分处理
    ErrorCode.PROVIDER_AUTH_FAILED: "fatal",      # 认证错误不可重试
    ErrorCode.PROVIDER_QUOTA_EXCEEDED: "fatal",   # 配额耗尽需人工干预
    ErrorCode.PROVIDER_CONTEXT_OVERFLOW: "fatal", # 上下文超限需裁剪
    
    # Middleware → RETRY（中间件故障通常是瞬时的）
    ErrorCode.MIDDLEWARE_REQUEST_FAILED: "retry",
    ErrorCode.MIDDLEWARE_TIMEOUT: "retry",
    
    # Validation → FATAL（参数错误不可重试）
    ErrorCode.VALIDATION_INVALID_CONFIG: "fatal",
    ErrorCode.VALIDATION_INVALID_MESSAGE: "fatal",
    
    # Timeout → RETRY（超时可能是临时的）
    ErrorCode.TIMEOUT_PROVIDER: "retry",
    ErrorCode.TIMEOUT_MIDDLEWARE: "retry",
    
    # Fallback → 根据情况
    ErrorCode.FALLBACK_TRIGGERED: "retry",        # 记录日志，继续重试
    ErrorCode.FALLBACK_EXHAUSTED: "fatal",        # 所有 Provider 失败
}
```

---

### 自定义重试策略

可以继承 `RetryPolicy` 类自定义分类逻辑：

```python
from onion_core.models import RetryPolicy, RetryOutcome

class CustomRetryPolicy(RetryPolicy):
    def classify_error(self, error: Exception, context) -> RetryOutcome:
        # 优先检查是否有错误码
        if hasattr(error, 'error_code'):
            error_code = error.error_code
            
            # 自定义规则：某些 Provider 错误可以重试
            if error_code == ErrorCode.PROVIDER_CONTENT_FILTER:
                return RetryOutcome.RETRY  # 内容过滤可能是误判
        
        #  fallback 到默认策略
        return super().classify_error(error, context)

# 使用
pipeline = Pipeline(
    provider=...,
    retry_policy=CustomRetryPolicy(),
)
```

---

## 错误码使用示例

### 1. 在中间件中抛出错误

```python
from onion_core.error_codes import ErrorCode, security_error

class SafetyGuardrailMiddleware(BaseMiddleware):
    async def process_request(self, context):
        # 检测关键词
        if self._contains_blocked_keyword(context):
            # ✅ 使用辅助函数创建带错误码的异常
            raise security_error(
                ErrorCode.SECURITY_BLOCKED_KEYWORD,
                details={"keyword": "blocked_word"}
            )
        
        return context
```

---

### 2. 在 Provider 中抛出错误

```python
from onion_core.error_codes import ErrorCode, provider_error

class OpenAIProvider(LLMProvider):
    async def complete(self, context):
        try:
            response = await self._client.post(...)
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # ✅ 认证失败
                raise provider_error(
                    ErrorCode.PROVIDER_AUTH_FAILED,
                    message=f"Invalid API key: {e}"
                )
            
            elif e.response.status_code == 429:
                # ✅ 限流
                raise provider_error(
                    ErrorCode.RATE_LIMIT_EXCEEDED,
                    message=f"Rate limit exceeded: {e}"
                )
        
        except httpx.TimeoutException:
            # ✅ 超时
            raise provider_error(
                ErrorCode.TIMEOUT_PROVIDER,
                message=f"Request timed out after {self._timeout}s"
            )
```

---

### 3. 捕获并处理错误

```python
from onion_core.error_codes import ErrorCode
from onion_core.models import OnionErrorWithCode

try:
    response = await pipeline.run(ctx)

except OnionErrorWithCode as e:
    # ✅ 根据错误码分类处理
    if e.error_code == ErrorCode.RATE_LIMIT_EXCEEDED:
        logger.warning(f"Rate limited, waiting...")
        await asyncio.sleep(60)
        response = await pipeline.run(ctx)  # 重试
    
    elif e.error_code == ErrorCode.PROVIDER_AUTH_FAILED:
        logger.error(f"Auth failed, check API key")
        send_alert("API Key Invalid")
    
    elif e.error_code.startswith("ONI-S"):
        # 所有安全类错误
        logger.warning(f"Security block: {e.error_code}")
        log_security_incident(e)
    
    else:
        raise  # 其他错误继续抛出
```

---

### 4. 监控和告警

#### Prometheus 指标

```python
from prometheus_client import Counter

error_counter = Counter(
    'onion_errors_total',
    'Total errors by error code',
    ['error_code', 'category']
)

def record_error(error: OnionErrorWithCode):
    category = error.error_code.split('-')[1][0]  # S, P, R, etc.
    error_counter.labels(
        error_code=error.error_code,
        category=category
    ).inc()
```

**查询示例**：
```promql
# 过去 5 分钟的安全错误数量
sum(rate(onion_errors_total{category="S"}[5m]))

# 最常见的 Provider 错误
topk(5, onion_errors_total{category="P"})
```

---

#### 日志检索

```bash
# 查找所有认证失败
grep "ONI-P400" /var/log/onion-core.log

# 统计每类错误的数量
grep -oP 'ONI-[A-Z]\d+' /var/log/onion-core.log | sort | uniq -c | sort -rn
```

输出：
```
  1234 ONI-P400  # 认证失败
   567 ONI-R200  # 限流
   234 ONI-T700  # 超时
   123 ONI-S102  # 提示词注入
```

---

## 错误码完整列表

### Security (100-199)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-S100` | SECURITY_BLOCKED_KEYWORD | 检测到拦截关键词 | FATAL |
| `ONI-S101` | SECURITY_PII_DETECTED | 检测到 PII 信息 | FATAL |
| `ONI-S102` | SECURITY_PROMPT_INJECTION | 检测到提示词注入 | FATAL |
| `ONI-S103` | SECURITY_FORBIDDEN_TOOL | 工具调用被禁止 | FATAL |

---

### Rate Limit (200-299)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-R200` | RATE_LIMIT_EXCEEDED | 超出 API 速率限制 | FALLBACK |
| `ONI-R201` | RATE_LIMIT_WINDOW_FULL | 时间窗口已满 | FALLBACK |

---

### Circuit Breaker (300-399)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-C300` | CIRCUIT_OPEN | 熔断器处于开启状态 | FALLBACK |
| `ONI-C301` | CIRCUIT_TRIPPED | 熔断器因连续失败而跳闸 | FALLBACK |

---

### Provider (400-499)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-P400` | PROVIDER_AUTH_FAILED | 认证失败（API Key 无效） | FATAL |
| `ONI-P401` | PROVIDER_QUOTA_EXCEEDED | 配额耗尽 | FATAL |
| `ONI-P402` | PROVIDER_MODEL_NOT_FOUND | 模型不存在 | FATAL |
| `ONI-P403` | PROVIDER_CONTENT_FILTER | 内容被过滤器拦截 | FATAL |
| `ONI-P404` | PROVIDER_CONTEXT_OVERFLOW | 超出上下文窗口 | FATAL |
| `ONI-P405` | PROVIDER_INVALID_REQUEST | 请求格式错误 | FATAL |

---

### Middleware (500-599)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-M500` | MIDDLEWARE_REQUEST_FAILED | 请求阶段中间件失败 | RETRY |
| `ONI-M501` | MIDDLEWARE_RESPONSE_FAILED | 响应阶段中间件失败 | RETRY |
| `ONI-M502` | MIDDLEWARE_STREAM_FAILED | 流式处理中间件失败 | RETRY |
| `ONI-M503` | MIDDLEWARE_TIMEOUT | 中间件执行超时 | RETRY |
| `ONI-M504` | MIDDLEWARE_CHAIN_ABORTED | 中间件链中断 | FATAL |

---

### Validation (600-699)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-V600` | VALIDATION_INVALID_CONFIG | 配置无效 | FATAL |
| `ONI-V601` | VALIDATION_INVALID_MESSAGE | 消息格式错误 | FATAL |
| `ONI-V602` | VALIDATION_INVALID_TOOL_CALL | 工具调用结构错误 | FATAL |
| `ONI-V603` | VALIDATION_INVALID_CONTEXT | 上下文缺少必需字段 | FATAL |

---

### Timeout (700-799)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-T700` | TIMEOUT_PROVIDER | Provider API 调用超时 | RETRY |
| `ONI-T701` | TIMEOUT_MIDDLEWARE | 中间件执行超时 | RETRY |
| `ONI-T702` | TIMEOUT_TOTAL_PIPELINE | 总请求超时 | FATAL |

---

### Fallback (800-899)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-F800` | FALLBACK_TRIGGERED | 触发 Fallback 切换 | RETRY |
| `ONI-F801` | FALLBACK_EXHAUSTED | 所有 Provider 失败 | FATAL |
| `ONI-F802` | FALLBACK_PROVIDER_FAILED | Fallback Provider 调用失败 | RETRY |

---

### Internal (900-999)

| 错误码 | 名称 | 说明 | 重试策略 |
|--------|------|------|---------|
| `ONI-I900` | INTERNAL_UNEXPECTED | 未预期的内部错误 | RETRY |
| `ONI-I901` | INTERNAL_NOT_IMPLEMENTED | 功能未实现 | FATAL |
| `ONI-I902` | INTERNAL_STATE_CORRUPT | 内部状态损坏 | FATAL |

---

## 最佳实践

### 1. 始终使用错误码

```python
# ❌ 错误：裸异常
raise Exception("Something went wrong")

# ✅ 正确：带错误码的异常
raise provider_error(ErrorCode.PROVIDER_AUTH_FAILED)
```

---

### 2. 提供详细的上下文信息

```python
# ❌ 信息不足
raise provider_error(ErrorCode.PROVIDER_QUOTA_EXCEEDED)

# ✅ 包含详细信息
raise provider_error(
    ErrorCode.PROVIDER_QUOTA_EXCEEDED,
    details={
        "provider": "OpenAI",
        "model": "gpt-4",
        "current_usage": 950000,
        "quota_limit": 1000000,
    }
)
```

---

### 3. 按类别设置告警阈值

```yaml
# Alertmanager 配置
groups:
  - name: onion-errors
    rules:
      - alert: HighSecurityErrors
        expr: rate(onion_errors_total{category="S"}[5m]) > 10
        annotations:
          summary: "High rate of security blocks"
      
      - alert: ProviderAuthFailures
        expr: increase(onion_errors_total{error_code="ONI-P400"}[1h]) > 5
        annotations:
          summary: "Multiple auth failures, check API keys"
```

---

### 4. 记录错误码到链路追踪

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("pipeline.run") as span:
    try:
        response = await pipeline.run(ctx)
    except OnionErrorWithCode as e:
        span.set_attribute("error.code", e.error_code)
        span.set_status(trace.StatusCode.ERROR)
        raise
```

---

## 总结

Onion Core 的错误码系统通过：
- ✅ **语义化命名**：清晰的错误分类
- ✅ **范围划分**：便于统计和告警
- ✅ **重试策略映射**：自动化错误处理
- ✅ **默认消息**：人类可读的错误描述

使得错误处理更加结构化、可观测和可维护。

---

## 延伸阅读

- [API 参考: ErrorCode](../api/error_codes.md)
- [操作指南: 设置 Fallback Providers](../how-to-guides/setup-fallback-providers.md)
- [背景解释: Pipeline 调度引擎](pipeline-scheduling.md)
