# API Reference - Middlewares

> **模块**: `onion_core.middlewares`  
> **版本**: v1.0.0

## BaseMiddleware

所有中间件的基类。

### 构造函数

```python
BaseMiddleware(
    name: str = "base",
    priority: int = 100,
    is_mandatory: bool = False,
)
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | `"base"` | 中间件名称 |
| `priority` | `int` | `100` | 优先级（数字越小越在外层） |
| `is_mandatory` | `bool` | `False` | 是否强制，失败时中断整个链路 |

### 必须实现的方法

#### process_request

请求阶段处理。

```python
async def process_request(self, context: AgentContext) -> AgentContext
```

**返回**: 修改后的 `AgentContext`（可以是原对象或新对象）

---

#### process_response

响应阶段处理。

```python
async def process_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse
```

**返回**: 修改后的 `LLMResponse`

---

### 可选实现的方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `process_stream_chunk` | `async def process_stream_chunk(context, chunk) -> StreamChunk` | 流式 chunk 处理 |
| `on_tool_call` | `async def on_tool_call(context, tool_call) -> ToolCall` | 工具调用拦截 |
| `on_tool_result` | `async def on_tool_result(context, result) -> ToolResult` | 工具结果拦截 |
| `on_error` | `async def on_error(context, error) -> None` | 错误通知钩子 |
| `startup` | `async def startup() -> None` | 中间件初始化 |
| `shutdown` | `async def shutdown() -> None` | 中间件清理 |

---

## SafetyGuardrailMiddleware

安全护栏中间件，提供 PII 脱敏、关键词拦截、提示词注入检测。

### 构造函数

```python
SafetyGuardrailMiddleware(
    enable_builtin_pii: bool = True,
    enable_input_pii_masking: bool = False,
    blocked_keywords: list[str] | None = None,
    custom_pii_rules: list[PiiRule] | None = None,
    pii_replacement: str = "***",
)
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_builtin_pii` | `bool` | `True` | 启用内置 PII 规则（手机号、邮箱、身份证等） |
| `enable_input_pii_masking` | `bool` | `False` | 是否脱敏输入（默认只脱敏输出） |
| `blocked_keywords` | `list[str] \| None` | `None` | 自定义拦截关键词列表 |
| `custom_pii_rules` | `list[PiiRule] \| None` | `None` | 自定义 PII 规则 |
| `pii_replacement` | `str` | `"***"` | PII 替换字符串 |

### 方法

#### add_pii_rule

添加自定义 PII 规则。

```python
def add_pii_rule(self, rule: PiiRule) -> None
```

**示例**:
```python
from onion_core.middlewares.safety import PiiRule
import re

ip_rule = PiiRule(
    name="ip_address",
    pattern=re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    replacement="[IP]",
)
safety_mw.add_pii_rule(ip_rule)
```

---

#### add_blocked_keyword

添加拦截关键词。

```python
def add_blocked_keyword(self, keyword: str) -> None
```

---

### 内置 PII 规则

| 规则名 | 匹配模式 | 示例 |
|--------|---------|------|
| `phone_number` | 中国大陆手机号 | `13812345678` → `***` |
| `email` | 邮箱地址 | `test@example.com` → `[email]` |
| `id_card` | 身份证号 | `110101199001011234` → `***` |
| `bank_card` | 银行卡号 | `6222021234567890123` → `***` |

---

## ContextWindowMiddleware

上下文窗口管理中间件，自动裁剪超长对话历史。

### 构造函数

```python
ContextWindowMiddleware(
    max_tokens: int = 4096,
    keep_rounds: int = 5,
    summary_strategy: Literal["rule-based", "llm"] = "rule-based",
    system_prompt_priority: Literal["always-keep", "trim-with-history"] = "always-keep",
)
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_tokens` | `int` | `4096` | 最大 Token 数 |
| `keep_rounds` | `int` | `5` | 保留最近 N 轮对话 |
| `summary_strategy` | `str` | `"rule-based"` | 摘要策略：`rule-based`（规则）或 `llm`（LLM 生成） |
| `system_prompt_priority` | `str` | `"always-keep"` | System Prompt 保留策略 |

### 元数据输出

裁剪后会在 `context.metadata` 中添加：

```python
{
    "token_count_before": 8234,   # 裁剪前 Token 数
    "token_count_after": 3892,    # 裁剪后 Token 数
    "context_truncated": True,    # 是否执行了裁剪
    "messages_removed": 42,       # 移除的消息数
}
```

---

## ObservabilityMiddleware

可观测性中间件，记录结构化日志和性能指标。

### 构造函数

```python
ObservabilityMiddleware(
    log_level: int = logging.INFO,
    enable_metrics: bool = True,
    enable_tracing: bool = True,
)
```

### 功能

- ✅ 自动记录请求/响应日志（JSON 格式）
- ✅ 注入 `request_id`, `trace_id`, `span_id` 到日志
- ✅ 计算并记录耗时（`duration_s`）
- ✅ 上报 Prometheus 指标（如果启用）
- ✅ 创建 OpenTelemetry Span（如果启用）

### 日志示例

```json
{
  "level": "INFO",
  "timestamp": "2026-04-27T10:30:45.123Z",
  "request_id": "abc123...",
  "trace_id": "def456...",
  "span_id": "ghi789...",
  "message": "Request completed",
  "duration_s": 1.234,
  "prompt_tokens": 120,
  "completion_tokens": 85,
  "total_tokens": 205
}
```

---

## DistributedRateLimitMiddleware

基于 Redis 的分布式限流中间件。

### 构造函数

```python
DistributedRateLimitMiddleware(
    redis_url: str = "redis://localhost:6379",
    max_requests: int = 60,
    window_seconds: float = 60.0,
    max_tool_calls: int | None = None,
    tool_call_window: float | None = None,
    key_prefix: str = "onion:ratelimit",
    pool_size: int = 10,
    fallback_allow: bool = False,
)
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `redis_url` | `str` | `"redis://localhost:6379"` | Redis 连接 URL |
| `max_requests` | `int` | `60` | 每窗口最大请求数 |
| `window_seconds` | `float` | `60.0` | 时间窗口（秒） |
| `max_tool_calls` | `int \| None` | `None` | 工具调用独立限额 |
| `tool_call_window` | `float \| None` | `None` | 工具调用时间窗口 |
| `key_prefix` | `str` | `"onion:ratelimit"` | Redis Key 前缀 |
| `pool_size` | `int` | `10` | Redis 连接池大小 |
| `fallback_allow` | `bool` | `False` | Redis 故障时是否允许通过 |

### 方法

#### get_usage

获取当前会话的限流使用情况。

```python
def get_usage(self, session_id: str) -> dict
```

**返回**:
```python
{
    "request_remaining": 45,
    "request_limit": 60,
    "tool_call_remaining": 18,
    "tool_call_limit": 20,
    "window_reset_at": 1714200000.0,
}
```

---

#### reset_session

重置特定会话的限流计数。

```python
async def reset_session(self, session_id: str) -> None
```

---

## DistributedCacheMiddleware

基于 Redis 的分布式响应缓存中间件。

### 构造函数

```python
DistributedCacheMiddleware(
    redis_url: str = "redis://localhost:6379",
    ttl: int = 3600,
    key_prefix: str = "onion:cache",
    pool_size: int = 10,
    cache_streaming: bool = False,
)
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ttl` | `int` | `3600` | 缓存过期时间（秒） |
| `cache_streaming` | `bool` | `False` | 是否缓存流式响应 |

### 缓存键生成

缓存键基于以下因素生成：
- 消息内容（序列化后哈希）
- Provider 模型名称
- Temperature 等采样参数

---

## DistributedCircuitBreakerMiddleware

基于 Redis 的分布式熔断器中间件。

### 构造函数

```python
DistributedCircuitBreakerMiddleware(
    redis_url: str = "redis://localhost:6379",
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    key_prefix: str = "onion:circuit",
)
```

### 状态转换

```
CLOSED ──(连续失败 ≥ threshold)──> OPEN
  ▲                                    │
  │                                    │ (recovery_timeout 后)
  │                                    ▼
  └──────────── HALF_OPEN <────────────┘
       │              │
       │ 成功         │ 失败
       ▼              ▼
    CLOSED          OPEN
```

---

## 相关文档

- [教程: 构建安全 Agent](../tutorials/02-secure-agent.md)
- [操作指南: 配置 Redis 分布式限流](../how-to-guides/configure-distributed-ratelimit.md)
- [背景解释: 洋葱模型设计哲学](../explanation/onion-model-philosophy.md)
