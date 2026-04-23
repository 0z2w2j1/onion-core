# Onion Core - Architecture Design Document

> Version: 0.6.0 | Date: 2026-04-24

## 1. Overview

Onion Core is an **onion-model middleware framework** for building reliable, secure, and observable AI Agent applications. It wraps LLM calls with layered protective middleware, following the principle of **defense in depth**.

```
                    ┌─────────────────────────────┐
                    │         User Request         │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────┐
              │  [1] Tracing     (priority=50)        │ ◄── Outer
              │  [2] Metrics     (priority=90)        │
              │  [3] Observability(priority=100)      │
              │  [4] Rate Limit  (priority=150, M)   │
              │  [5] Safety      (priority=200, M)    │
              │  [6] Context     (priority=300)       │
              └──────────────┬───────────────────────┘
                             │
                             ▼
                    [ LLM Provider Call ]
                             │
                             ▼
              ┌────────────────────────────────────────┐
              │  [6] Context     (priority=300)       │
              │  [5] Safety      (priority=200, M)    │
              │  [4] Rate Limit  (priority=150, M)   │
              │  [3] Observability(priority=100)      │
              │  [2] Metrics     (priority=90)        │
              │  [1] Tracing     (priority=50)        │ ◄── Inner
              └──────────────┬───────────────────────┘
                             │
                             ▼
                    ┌─────────────────────────────┐
                    │        User Response          │
                    └─────────────────────────────┘
              M = is_mandatory = True (failure breaks chain)
```

---

## 2. Design Principles

| Principle | Description |
|-----------|-------------|
| **Onion Model** | Request flows inward through middleware (ascending priority), response flows outward (descending priority) |
| **Defense in Depth** | Multiple independent security/reliability layers; one layer failing doesn't compromise the whole |
| **Fail-Safe Defaults** | Middleware default to `is_mandatory=False` (fault isolation); security layers are mandatory |
| **Observable by Default** | Structured JSON logging, Prometheus metrics, and OpenTelemetry tracing are built-in |
| **Provider Agnostic** | `LLMProvider` abstract interface; swap providers without changing business logic |
| **Async First** | All I/O operations are `async/await` native; proper `asyncio` timeouts throughout |

---

## 3. Core Components

### 3.1 Pipeline (`pipeline.py`)

The **central orchestrator**. Manages middleware chain execution, provider calls, retry logic, circuit breaking, and fallback provider chaining.

**Key Responsibilities:**
- Middleware chain ordering (by `priority` ascending for request, descending for response)
- Per-middleware timeout management
- Provider call with exponential backoff retry
- Circuit breaker integration (per-provider state machine)
- Fallback provider chaining (primary → fallback1 → fallback2 → ...)
- Error notification broadcast to all middlewares

**State Machine (Retry + Fallback):**
```
Provider Call
  │
  ├─ Success → return LLMResponse
  ├─ RETRY (transient) → wait (base_delay × 2^attempt + jitter) → retry
  │   └─ max_retries exhausted → next fallback provider
  ├─ FALLBACK (service error, circuit open) → next fallback provider
  └─ FATAL (security, bad params) → raise immediately
```

---

### 3.2 Middleware System (`base.py`)

All middleware **must** implement:
- `process_request(context) → AgentContext`
- `process_response(context, response) → LLMResponse`

All middleware **may** optionally override:
- `process_stream_chunk(context, chunk) → StreamChunk`
- `on_tool_call(context, tool_call) → ToolCall`
- `on_tool_result(context, result) → ToolResult`
- `on_error(context, error) → None`

**Fault Isolation:**
- `is_mandatory = False` (default): failure → log + continue chain
- `is_mandatory = True`: failure → log + raise immediately

---

### 3.3 Provider Abstraction (`provider.py`, `providers/`)

```
LLMProvider (abstract)
  ├── EchoProvider          (built-in test double)
  ├── OpenAIProvider       (OpenAI API)
  │     ├── DeepSeekProvider   (DeepSeek API, preset base_url)
  │     ├── ZhipuAIProvider   (Zhipu GLM, preset base_url)
  │     ├── MoonshotProvider  (Kimi, preset base_url)
  │     ├── DashScopeProvider (Qwen/Tongyi, preset base_url)
  │     └── LocalProvider      (generic OpenAI-compatible)
  │           ├── OllamaProvider   (localhost:11434)
  │           └── LMStudioProvider (localhost:1234)
  └── AnthropicProvider    (Anthropic API)
```

All providers implement:
```python
async def complete(self, context: AgentContext) -> LLMResponse
async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]
```

---

### 3.4 Configuration System (`config.py`)

`OnionConfig` extends Pydantic `BaseSettings`, supporting three configuration sources with priority:

1. **Code** (highest priority)
2. **Environment Variables** (prefix: `ONION__`)
3. **JSON/YAML File** (lowest priority)

```python
config = OnionConfig(
    pipeline=PipelineConfig(max_retries=3, provider_timeout=30.0),
    safety=SafetyConfig(enable_pii_masking=True),
)
# Or from file:
config = OnionConfig.from_file("onion.json")
# Or from env:
config = OnionConfig.from_env()  # reads ONION__*
```

---

### 3.5 Error Handling (`models.py`, `error_codes.py`)

#### Exception Hierarchy
```
Exception
  └── OnionError              (base for all onion errors)
        ├── SecurityException  (is_fatal=True)
        ├── RateLimitExceeded  (is_fatal=True)
        ├── ProviderError      (is_fatal=False)
        └── CircuitBreakerError(is_fatal=False)

  └── OnionErrorWithCode     (NEW: includes ErrorCode + metadata)
        code: ErrorCode
        extra: Dict[str, Any]
        retry_outcome: RetryOutcome
```

#### RetryOutcome Decision Matrix
| Exception Type | `is_fatal` | `RetryPolicy.classify()` | Action |
|---------------|------------|-------------------------|--------|
| `SecurityException` | True | `FATAL` | Raise immediately |
| `RateLimitExceeded` | True | `FALLBACK` | Next fallback provider |
| `CircuitBreakerError` | False | `FALLBACK` | Next fallback provider |
| `ProviderError` | False | `RETRY` | Exponential backoff |
| `ValueError/TypeError` | — | `FATAL` | Raise immediately |
| `asyncio.TimeoutError` | — | `RETRY` | Exponential backoff |

---

### 3.6 Circuit Breaker (`circuit_breaker.py`)

Per-provider state machine:

```
        failure_count >= threshold
  [CLOSED] ───────────────────────► [OPEN]
     ▲                                   │
     │                                   │ recovery_timeout elapsed
     │  success_count >= success_threshold│
  [HALF_OPEN] ◄───────────────────────┘
     │
     └── 1 failure in HALF_OPEN ──────► [OPEN]
```

**Configuration:**
- `failure_threshold`: 5 (trips after 5 consecutive failures)
- `recovery_timeout`: 30.0s (OPEN → HALF_OPEN after this)
- `success_threshold`: 2 (HALF_OPEN → CLOSED after 2 consecutive successes)

---

### 3.7 Agent Loop (`agent.py`)

Orchestrates multi-turn conversations with automatic tool execution:

```
AgentLoop.run(context)
  │
  └─ loop (max_turns=10):
        response = await pipeline.run(context)
        ├─ has_tool_calls → execute each tool → append results → continue
        └─ is_complete → return response
```

---

## 4. Data Flow

### 4.1 Non-Streaming Request
```
User Code
  │
  └─ Pipeline.run(context)
       │
       ├─ [1] middleware.process_request()  ← ascending priority (50→300)
       │     └─ if failure:
       │          ├─ mandatory → raise (chain breaks)
       │          └─ non-mandatory → log + continue
       │
       ├─ Provider.complete(context)
       │     ├─ Success → LLMResponse
       │     ├─ RETRY → wait + retry (max_retries)
       │     ├─ FALLBACK → try next fallback provider
       │     └─ FATAL → raise
       │
       └─ [2] middleware.process_response() ← descending priority (300→50)
            └─ return final LLMResponse to user
```

### 4.2 Streaming Request
```
User Code
  │
  └─ async for chunk in Pipeline.stream(context):
       │
       ├─ [1] middleware.process_request()  ← ascending priority
       │
       ├─ async for raw_chunk in Provider.stream(context):
       │     └─ [2] middleware.process_stream_chunk() ← descending priority
       │          └─ yield filtered chunk to user
       │
       └─ [3] middleware.process_response() if finish_reason set
```

---

## 5. Middleware Priority Table

| Priority | Middleware | Mandatory | Purpose |
|----------|-----------|-----------|---------|
| 50 | `TracingMiddleware` | No | OpenTelemetry distributed tracing |
| 90 | `MetricsMiddleware` | No | Prometheus metrics collection |
| 100 | `ObservabilityMiddleware` | No | JSON structured logging, timing |
| 150 | `RateLimitMiddleware` | **Yes** | Sliding window rate limiting |
| 200 | `SafetyGuardrailMiddleware` | **Yes** | PII masking, injection detection |
| 300 | `ContextWindowMiddleware` | No | Token counting, context truncation |

---

## 6. Extensibility

### 6.1 Custom Middleware
```python
class MyMiddleware(BaseMiddleware):
    priority = 175  # between RateLimit(150) and Safety(200)

    async def process_request(self, context):
        # your logic here
        return context

    async def process_response(self, context, response):
        return response
```

### 6.2 Custom Provider
```python
class MyProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    async def complete(self, context):
        # call your LLM API here
        return LLMResponse(content="...", model=self._model)

    async def stream(self, context):
        # yield StreamChunk objects
        yield StreamChunk(delta="...")
```

### 6.3 Custom Error Codes
```python
from enum import Enum
from onion_core.error_codes import ERROR_MESSAGES, ERROR_RETRY_POLICY, RetryOutcome

class MyErrorCode(str, Enum):
    CUSTOM_BUSINESS_RULE = "ONI-B100"  # B = Business

ERROR_MESSAGES[MyErrorCode.CUSTOM_BUSINESS_RULE] = "Business rule violation"
ERROR_RETRY_POLICY()[MyErrorCode.CUSTOM_BUSINESS_RULE] = RetryOutcome.FATAL
```

---

## 7. Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Data Validation | Pydantic v2 |
| Token Counting | tiktoken |
| Logging | standard `logging` + custom `JsonFormatter` |
| Metrics | Prometheus (`prometheus-client`, optional) |
| Tracing | OpenTelemetry (`opentelemetry-api/sdk`, optional) |
| Testing | pytest + pytest-asyncio |
| Linting | Ruff |
| Type Checking | MyPy (strict mode) |
| Build System | setuptools |

---

## 8. Thread Safety & Concurrency

- `Pipeline` uses `asyncio.Lock()` for startup/shutdown and dynamic middleware registration
- `CircuitBreaker` uses `asyncio.Lock()` for state transitions
- `RateLimitMiddleware` uses `asyncio.Lock()` + `OrderedDict` (LRU) for session windows
- All provider calls support `asyncio.wait_for()` timeouts
- `ContextVar` is used for trace_id propagation (safe across concurrent coroutines)

---

## 9. Limitations (v0.6.0)

| Area | Limitation |
|------|------------|
| **Distributed state** | Circuit breaker and rate limiter are in-memory only (single process) |
| **Version** | 0.6.0 (Beta) — API may change without notice |
| **Documentation** | Primarily Chinese README; English docs added in this release |
| **CI/CD** | GitHub Actions configured for testing and linting |

---

## 10. Performance Optimizations (v0.6.0+)

### 10.1 LRU Cache for Token Encoding

`ContextWindowMiddleware` uses an LRU cache (`OrderedDict`) to store tiktoken encoding objects:
- **Cache size**: 10 encodings maximum
- **Eviction policy**: Least Recently Used (LRU)
- **Benefit**: Avoids repeated `tiktoken.get_encoding()` calls, which are expensive (~50-100ms)
- **Memory safety**: Prevents unbounded memory growth

```python
# Internal implementation
self._encoding_cache: OrderedDict[str, tiktoken.Encoding] = OrderedDict()
# On cache hit: move to end (most recently used)
self._encoding_cache.move_to_end(name)
# On cache miss: add new, evict oldest if full
if len(self._encoding_cache) > ENCODING_CACHE_MAX_SIZE:
    self._encoding_cache.popitem(last=False)
```

### 10.2 Pre-compiled PII Regex Patterns

`SafetyGuardrailMiddleware` pre-compiles all PII detection regex patterns at module load time:
- **Patterns compiled once**: Email, phone (CN/intl), ID card, credit card
- **No runtime compilation overhead**: `re.compile()` called during import
- **Thread-safe**: Compiled patterns are immutable and shared

```python
# Module-level pre-compilation (safety.py line 25-31)
BUILTIN_PII_RULES: list[PiiRule] = [
    PiiRule("email", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), ...),
    PiiRule("phone_cn", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), ...),
    # ... more patterns
]
```

### 10.3 Exception Aggregation

When all providers (primary + fallbacks) fail, the pipeline now:
- **Collects all exceptions**: Stores `(provider_name, exception)` tuples
- **Logs comprehensive error summary**: Shows all failures in one log entry
- **Raises last exception**: Maintains backward compatibility while preserving context

This improves debugging by showing the complete failure chain instead of just the last error.

### 10.4 Health Check Endpoint

New `Pipeline.health_check()` method provides observability into pipeline state:
- **Status codes**: `healthy`, `not_started`, `degraded`
- **Circuit breaker monitoring**: Reports state of each provider's breaker
- **Degradation detection**: Automatically marks as "degraded" if any breaker is OPEN
- **Use case**: Kubernetes liveness/readiness probes, monitoring dashboards

```python
health = pipeline.health_check()
# {
#     "status": "degraded",
#     "name": "my-pipeline",
#     "started": True,
#     "middlewares_count": 3,
#     "provider": "OpenAIProvider",
#     "fallback_providers": ["DeepSeekProvider"],
#     "circuit_breakers": {
#         "OpenAIProvider": "open",  # Tripped!
#         "DeepSeekProvider": "closed"
#     }
# }
```

---

# Onion Core - 架构设计文档

> 版本：0.6.0 | 日期：2026-04-24

## 1. 概述

Onion Core 是一个用于构建可靠、安全、可观测的 AI Agent 应用的**洋葱模型中间件框架**。它采用**纵深防御**原则，用分层protective middleware 包裹 LLM 调用。

```
                    ┌─────────────────────────────┐
                    │         用户请求             │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
               ┌────────────────────────────────────────┐
               │  [1] 链路追踪     (priority=50)        │ ◄── 外层
               │  [2] 性能监控   (priority=90)        │
               │  [3] 可观测性   (priority=100)      │
               │  [4] 限流保护 (priority=150, M)    │
               │  [5] 安全护栏 (priority=200, M)   │
               │  [6] 上下文管理 (priority=300)     │
               └──────────────┬───────────────────────┘
                             │
                             ▼
                      [ LLM Provider 调用]
                             │
                             ▼
               ┌────────────────────────────────────────┐
               │  [6] 上下文管理 (priority=300)     │
               │  [5] 安全护栏 (priority=200, M)   │
               │  [4] 限流保护 (priority=150, M)    │
               │  [3] 可观测性 (priority=100)       │
               │  [2] 性能监控   (priority=90)      │
               │  [1] 链路追踪   (priority=50)     │ ◄── 内层
               └──────────────┬───────────────────────┘
                             │
                             ▼
                    ┌─────────────────────────────┐
                    │         用户响应             │
                    └─────────────────────────────┘
               M = is_mandatory = True (失败中断链路)
```

---

## 2. 设计原则

| 原则 | 说明 |
|------|------|
| **洋葱模型** | 请求按优先级升序流经中间件，响应按优先级降序流出 |
| **纵深防御** | 多层独立安全/可靠性层；一层失败不影响整体 |
| **故障安全默认** | 中间件默认 `is_mandatory=False`（故障隔离）；安全层为 mandatory |
| **默认可观测** | 内置结构化 JSON 日志、Prometheus 指标、OpenTelemetry 链路追踪 |
| **Provider 无关** | `LLMProvider` 抽象接口；无需更改业务逻辑即可切换 Provider |
| **异步优先** | 所有 I/O 操作原生 `async/await`；全程 proper `asyncio` 超时 |

---

## 3. 核心组件

### 3.1 Pipeline (`pipeline.py`)

**核心调度器**。管理中间件链执行、Provider 调用、重试逻辑、熔断和 Fallback Provider 链。

**主要职责：**
- 中间件链排序（请求阶段按 `priority` 升序，响应阶段按降序）
- 单中间件超时管理
- Provider 调用与指数退避重试
- 熔断器集成（per-provider 状态机）
- Fallback Provider 链（primary → fallback1 → fallback2 → ...）
- 错误通知广播到所有中间件

**状态机（重试 + Fallback）：**
```
Provider 调用
  │
  ├─ 成功 → 返回 LLMResponse
  ├─ RETRY（瞬时故障）→ 等待 (base_delay × 2^attempt + jitter) → 重试
  │   └─ max_retries 用尽 → 下一个 fallback provider
  ├─ FALLBACK（服务错误、熔断打开）→ 下一个 fallback provider
  └─ FATAL（安全、错误参数）→ 立即抛出
```

---

### 3.2 中间件系统 (`base.py`)

所有中间件**必须**实现：
- `process_request(context) → AgentContext`
- `process_response(context, response) → LLMResponse`

所有中间件**可以**选择性覆盖：
- `process_stream_chunk(context, chunk) → StreamChunk`
- `on_tool_call(context, tool_call) → ToolCall`
- `on_tool_result(context, result) → ToolResult`
- `on_error(context, error) → None`

**故障隔离：**
- `is_mandatory = False`（默认）：失败 → 记录日志 + 继续链路
- `is_mandatory = True`：失败 → 记录日志 + 立即抛出

---

### 3.3 Provider 抽象 (`provider.py`, `providers/`)

```
LLMProvider (抽象)
  ├── EchoProvider          (内置测试 double)
  ├── OpenAIProvider       (OpenAI API)
  │     ├── DeepSeekProvider   (DeepSeek API, 预设 base_url)
  │     ├── ZhipuAIProvider   (智谱 GLM, 预设 base_url)
  │     ├── MoonshotProvider  (Kimi, 预设 base_url)
  │     ├── DashScopeProvider (通义/千问, 预设 base_url)
  │     └── LocalProvider      (通用 OpenAI 兼容)
  │           ├── OllamaProvider   (localhost:11434)
  │           └── LMStudioProvider (localhost:1234)
  └── AnthropicProvider    (Anthropic API)
```

所有 Provider 实现：
```python
async def complete(self, context: AgentContext) -> LLMResponse
async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]
```

---

### 3.4 配置系统 (`config.py`)

`OnionConfig` 继承 Pydantic `BaseSettings`，支持三种配置来源（优先级）：

1. **代码**（最高优先级）
2. **环境变量**（前缀：`ONION__`）
3. **JSON/YAML 文件**（最低优先级）

```python
config = OnionConfig(
    pipeline=PipelineConfig(max_retries=3, provider_timeout=30.0),
    safety=SafetyConfig(enable_pii_masking=True),
)
# 或从文件：
config = OnionConfig.from_file("onion.json")
# 或从环境变量：
config = OnionConfig.from_env()  # 读取 ONION__*
```

---

### 3.5 错误处理 (`models.py`, `error_codes.py`)

#### 异常层次
```
Exception
  └── OnionError              (所有 onion 错误的基础)
        ├── SecurityException  (is_fatal=True)
        ├── RateLimitExceeded  (is_fatal=True)
        ├── ProviderError      (is_fatal=False)
        └── CircuitBreakerError(is_fatal=False)

  └── OnionErrorWithCode     (新增：包含 ErrorCode + 元数据)
        code: ErrorCode
        extra: Dict[str, Any]
        retry_outcome: RetryOutcome
```

#### RetryOutcome 决策矩阵
| 异常类型 | `is_fatal` | `RetryPolicy.classify()` | 动作 |
|---------------|------------|-------------------------|--------|
| `SecurityException` | True | `FATAL` | 立即抛出 |
| `RateLimitExceeded` | True | `FALLBACK` | 下一个 fallback |
| `CircuitBreakerError` | False | `FALLBACK` | 下一个 fallback |
| `ProviderError` | False | `RETRY` | 指数退避 |
| `ValueError/TypeError` | — | `FATAL` | 立即抛出 |
| `asyncio.TimeoutError` | — | `RETRY` | 指数退避 |

---

### 3.6 熔断器 (`circuit_breaker.py`)

Per-provider 状态机：

```
         连续失败 >= threshold
   [CLOSED] ───────────────────────► [OPEN]
      ▲                                   │
      │                                   │ recovery_timeout 流逝
      │  连续成功 >= success_threshold   │
   [HALF_OPEN] ◄───────────────────────┘
      │
      └── HALF_OPEN 期 1 次失败 ──────► [OPEN]
```

**配置：**
- `failure_threshold`: 5（连续 5 次失败后触发）
- `recovery_timeout`: 30.0s（OPEN → HALF_OPEN 等待时间）
- `success_threshold`: 2（HALF_OPEN → CLOSED 需要 2 次连续成功）

---

### 3.7 Agent Loop (`agent.py`)

编排多轮对话，自动执行工具：

```
AgentLoop.run(context)
  │
  └─ 循环 (max_turns=10):
        response = await pipeline.run(context)
        ├─ has_tool_calls → 执行每个工具 → 追加结果 → 继续
        └─ is_complete → 返回 response
```

---

## 4. 数据流

### 4.1 非流式请求
```
用户代码
  │
  └─ Pipeline.run(context)
       │
       ├─ [1] middleware.process_request()  ← 优先级升序 (50→300)
       │     └─ 若失败：
       │          ├─ mandatory → 抛出（链路中断）
       │          └─ non-mandatory → 记录 + 继续
       │
       ├─ Provider.complete(context)
       │     ├─ 成功 → LLMResponse
       │     ├─ RETRY → 等待 + 重试 (max_retries)
       │     ├─ FALLBACK → 尝试下一个 fallback
       │     └─ FATAL → 抛出
       │
       └─ [2] middleware.process_response() ← 优先级降序 (300→50)
            └─ 返回最终 LLMResponse 给用户
```

### 4.2 流式请求
```
用户代码
  │
  └─ async for chunk in Pipeline.stream(context):
       │
       ├─ [1] middleware.process_request()  ← 优先级升序
       │
       ├─ async for raw_chunk in Provider.stream(context):
       │     └─ [2] middleware.process_stream_chunk() ← 优先级降序
       │          └─ 过滤后的 chunk 产出给用户
       │
       └─ [3] middleware.process_response() 若 finish_reason 已设置
```

---

## 5. 中间件优先级表

| 优先级 | 中间件 | 强制 | 用途 |
|----------|-----------|-----------|---------|
| 50 | `TracingMiddleware` | 否 | OpenTelemetry 分布式链路追踪 |
| 90 | `MetricsMiddleware` | 否 | Prometheus 指标收集 |
| 100 | `ObservabilityMiddleware` | 否 | JSON 结构化日志、耗时统计 |
| 150 | `RateLimitMiddleware` | **是** | 滑动窗口限流 |
| 200 | `SafetyGuardrailMiddleware` | **是** | PII 脱敏、注入检测 |
| 300 | `ContextWindowMiddleware` | 否 | Token 计数、上下文裁剪 |

---

## 6. 扩展性

### 6.1 自定义中间件
```python
class MyMiddleware(BaseMiddleware):
    priority = 175  # 介于限流(150)和安全(200)之间

    async def process_request(self, context):
        # 在此添加您的逻辑
        return context

    async def process_response(self, context, response):
        return response
```

### 6.2 自定义 Provider
```python
class MyProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    async def complete(self, context):
        # 在此调用您的 LLM API
        return LLMResponse(content="...", model=self._model)

    async def stream(self, context):
        # 产出 StreamChunk 对象
        yield StreamChunk(delta="...")
```

### 6.3 自定义错误码
```python
from enum import Enum
from onion_core.error_codes import ERROR_MESSAGES, ERROR_RETRY_POLICY, RetryOutcome

class MyErrorCode(str, Enum):
    CUSTOM_BUSINESS_RULE = "ONI-B100"  # B = Business

ERROR_MESSAGES[MyErrorCode.CUSTOM_BUSINESS_RULE] = "业务规则违反"
ERROR_RETRY_POLICY()[MyErrorCode.CUSTOM_BUSINESS_RULE] = RetryOutcome.FATAL
```

---

## 7. 技术栈

| 层级 | 技术 |
|-------|------------|
| 语言 | Python 3.11+ |
| 数据验证 | Pydantic v2 |
| Token 计数 | tiktoken |
| 日志 | 标准 `logging` + 自定义 `JsonFormatter` |
| 指标 | Prometheus (`prometheus-client`，可选) |
| 链路追踪 | OpenTelemetry (`opentelemetry-api/sdk`，可选) |
| 测试 | pytest + pytest-asyncio |
| 代码检查 | Ruff |
| 类型检查 | MyPy（严格模式） |
| 构建系统 | setuptools |

---

## 8. 线程安全与并发

- `Pipeline` 使用 `asyncio.Lock()` 用于 startup/shutdown 和动态中间件注册
- `CircuitBreaker` 使用 `asyncio.Lock()` 用于状态转换
- `RateLimitMiddleware` 使用 `asyncio.Lock()` + `OrderedDict`（LRU）管理会话窗口
- 所有 Provider 调用支持 `asyncio.wait_for()` 超时
- `ContextVar` 用于 trace_id 传播（协程间安全）

---

## 9. 限制 (v0.6.0)

| 领域 | 限制 |
|------|------------|
| **分布式状态** | 熔断器和限流器仅内存存在（单进程） |
| **版本** | 0.6.0（Beta）— API 可能随时变更 |
| **文档** | 主要中文 README；本版本添加英文文档 |
| **CI/CD** | GitHub Actions 已配置用于测试和代码检查 |

---

## 10. 性能优化 (v0.6.0+)

### 10.1 Token Encoding 的 LRU 缓存

`ContextWindowMiddleware` 使用 LRU 缓存（`OrderedDict`）存储 tiktoken encoding 对象：
- **缓存容量**：最多 10 个 encodings
- **淘汰策略**：最近最少使用（LRU）
- **性能收益**：避免重复调用 `tiktoken.get_encoding()`，每次调用约需 50-100ms
- **内存安全**：防止无限制的内存增长

```python
# 内部实现
self._encoding_cache: OrderedDict[str, tiktoken.Encoding] = OrderedDict()
# 缓存命中：移动到末尾（最近使用）
self._encoding_cache.move_to_end(name)
# 缓存未命中：添加新项，如果满了则删除最旧的
if len(self._encoding_cache) > ENCODING_CACHE_MAX_SIZE:
    self._encoding_cache.popitem(last=False)
```

### 10.2 PII 正则表达式预编译

`SafetyGuardrailMiddleware` 在模块加载时预编译所有 PII 检测正则表达式：
- **一次性编译**：邮箱、手机号（国内/国际）、身份证、信用卡
- **无运行时开销**：`re.compile()` 在导入时调用
- **线程安全**：编译后的模式是不可变的且可共享

```python
# 模块级预编译（safety.py 第 25-31 行）
BUILTIN_PII_RULES: list[PiiRule] = [
    PiiRule("email", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), ...),
    PiiRule("phone_cn", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), ...),
    # ... 更多模式
]
```

### 10.3 异常聚合

当所有 Provider（主 Provider + Fallback）都失败时，Pipeline 现在会：
- **收集所有异常**：存储 `(provider_name, exception)` 元组
- **记录完整错误摘要**：在一个日志条目中显示所有失败
- **抛出最后一个异常**：保持向后兼容性同时保留上下文

这通过显示完整的失败链而不仅仅是最后一个错误来改善调试体验。

### 10.4 健康检查端点

新增 `Pipeline.health_check()` 方法提供 Pipeline 状态的可观测性：
- **状态码**：`healthy`（健康）、`not_started`（未启动）、`degraded`（降级）
- **熔断器监控**：报告每个 Provider 的熔断器状态
- **降级检测**：如果任何熔断器处于 OPEN 状态则自动标记为“降级”
- **使用场景**：Kubernetes liveness/readiness probes、监控仪表板

```python
health = pipeline.health_check()
# {
#     "status": "degraded",
#     "name": "my-pipeline",
#     "started": True,
#     "middlewares_count": 3,
#     "provider": "OpenAIProvider",
#     "fallback_providers": ["DeepSeekProvider"],
#     "circuit_breakers": {
#         "OpenAIProvider": "open",  # 熔断了！
#         "DeepSeekProvider": "closed"
#     }
# }
```
