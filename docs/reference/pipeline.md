# API Reference - Pipeline

> **模块**: `onion_core.pipeline`  
> **版本**: v1.0.0

## Pipeline

核心调度引擎，负责中间件编排、Provider 调用、重试与熔断。

### 构造函数

```python
Pipeline(
    provider: LLMProvider,
    name: str = "default",
    middleware_timeout: float | None = None,
    provider_timeout: float | None = None,
    total_timeout: float | None = None,
    max_retries: int = 0,
    retry_base_delay: float = 0.5,
    fallback_providers: list[LLMProvider] | None = None,
    retry_policy: RetryPolicy | None = None,
    enable_circuit_breaker: bool = True,
    circuit_failure_threshold: int = 5,
    circuit_recovery_timeout: float = 30.0,
    max_stream_chunks: int = 10000,
    owns_provider: bool = True,
)
```

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `provider` | `LLMProvider` | **必需** | 主 LLM Provider 实例 |
| `name` | `str` | `"default"` | Pipeline 名称，用于 Metrics/Traces 标签 |
| `middleware_timeout` | `float \| None` | `None` | 单个中间件调用超时（秒），`None` 表示不限制 |
| `provider_timeout` | `float \| None` | `None` | Provider 调用超时（秒） |
| `total_timeout` | `float \| None` | `None` | 整个请求的总超时（包括所有中间件 + Provider） |
| `max_retries` | `int` | `0` | Provider 失败时的最大重试次数（指数退避） |
| `retry_base_delay` | `float` | `0.5` | 重试基础延迟（秒），实际延迟 = base × 2^attempt + jitter |
| `fallback_providers` | `list[LLMProvider] \| None` | `None` | 备用 Provider 列表，主 Provider 全部失败后依次尝试 |
| `retry_policy` | `RetryPolicy \| None` | `RetryPolicy()` | 自定义重试决策器 |
| `enable_circuit_breaker` | `bool` | `True` | 是否启用熔断机制 |
| `circuit_failure_threshold` | `int` | `5` | 熔断触发阈值（连续失败次数） |
| `circuit_recovery_timeout` | `float` | `30.0` | 熔断恢复超时（秒） |
| `max_stream_chunks` | `int` | `10000` | 流式响应最大 chunk 数，防止 DoS 攻击 |
| `owns_provider` | `bool` | `True` | 是否由 Pipeline 管理 Provider 生命周期 |

### 方法

#### add_middleware

注册中间件，支持链式调用。应在 `startup()` 前完成。

```python
def add_middleware(self, middleware: BaseMiddleware) -> Pipeline
```

**参数**:
- `middleware`: 要注册的中间件实例

**返回**: `Pipeline` 自身（支持链式调用）

**示例**:
```python
p = Pipeline(provider=OpenAIProvider())
p.add_middleware(ObservabilityMiddleware()) \
 .add_middleware(SafetyGuardrailMiddleware())
```

---

#### add_middleware_async

运行时并发安全注册中间件。

```python
async def add_middleware_async(self, middleware: BaseMiddleware) -> Pipeline
```

**特点**:
- 使用 `asyncio.Lock` 保护，线程安全
- 如果 Pipeline 已启动，会自动调用中间件的 `startup()`

---

#### run

执行完整的请求-响应周期。

```python
async def run(self, context: AgentContext) -> LLMResponse
```

**参数**:
- `context`: 请求上下文，包含消息列表和元数据

**返回**: `LLMResponse` - LLM 的响应

**异常**:
- `SecurityException`: 安全拦截（关键词、PII、注入攻击）
- `RateLimitExceeded`: 超出速率限制
- `CircuitBreakerError`: 熔断器开启
- `ProviderError`: Provider 调用失败（重试耗尽后）
- `TimeoutError`: 超时（中间件/Provider/总超时）

**示例**:
```python
ctx = AgentContext(messages=[
    Message(role="user", content="你好")
])
response = await p.run(ctx)
print(response.content)
```

---

#### stream

流式执行请求，逐块返回响应。

```python
async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]
```

**参数**:
- `context`: 请求上下文

**返回**: `AsyncIterator[StreamChunk]` - 异步迭代器，逐个产生 chunk

**示例**:
```python
async for chunk in p.stream(ctx):
    if chunk.delta:
        print(chunk.delta, end="", flush=True)
```

---

#### run_sync

同步版本的 `run()`，适用于 Flask/Django 等同步框架。

```python
def run_sync(self, context: AgentContext, timeout: float | None = None) -> LLMResponse
```

**参数**:
- `context`: 请求上下文
- `timeout`: 可选的超时时间（秒），覆盖 Pipeline 配置

**注意**:
- **不能**在 async 上下文中调用（会抛出 `RuntimeError`）
- 内部创建新的事件循环，有少量性能开销

**示例**:
```python
# Flask 路由
@app.route("/chat", methods=["POST"])
def chat():
    ctx = AgentContext(messages=[...])
    response = pipeline.run_sync(ctx)
    return jsonify({"content": response.content})
```

---

#### stream_sync

同步版本的 `stream()`。

```python
def stream_sync(self, context: AgentContext, timeout: float | None = None) -> Iterator[StreamChunk]
```

**注意**:
- 内部缓冲最多 `max_stream_chunks` 个 chunk（默认 10000）
- 内存占用较高，优先使用异步 `stream()`

---

#### startup

手动启动 Pipeline（初始化中间件）。

```python
async def startup(self) -> None
```

**说明**:
- 使用 `async with Pipeline(...)` 时自动调用
- 手动调用时需配合 `shutdown()`

---

#### shutdown

关闭 Pipeline，清理资源。

```python
async def shutdown(self) -> None
```

**清理内容**:
- 调用所有中间件的 `shutdown()`
- 如果 `owns_provider=True`，调用 Provider 的 `cleanup()`
- 关闭 HTTP 连接池

---

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | Pipeline 名称 |
| `middlewares` | `list[BaseMiddleware]` | 已注册的中间件列表（按优先级排序） |
| `provider` | `LLMProvider` | 主 Provider 实例 |

---

### 完整示例

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider
from onion_core.middlewares import (
    ObservabilityMiddleware,
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
)

async def main():
    # 创建 Pipeline
    async with Pipeline(
        provider=OpenAIProvider(api_key="sk-...", model="gpt-4"),
        name="production-pipeline",
        max_retries=3,
        provider_timeout=30.0,
        total_timeout=60.0,
        enable_circuit_breaker=True,
    ) as p:
        # 添加中间件（洋葱模型）
        p.add_middleware(ObservabilityMiddleware())       # priority=100
        p.add_middleware(SafetyGuardrailMiddleware())     # priority=200
        p.add_middleware(ContextWindowMiddleware(         # priority=300
            max_tokens=8000,
            keep_rounds=5
        ))
        
        # 执行请求
        ctx = AgentContext(messages=[
            Message(role="user", content="解释量子计算")
        ])
        
        response = await p.run(ctx)
        print(f"回复: {response.content}")
        print(f"Token 使用: {response.usage.total_tokens}")
        print(f"耗时: {ctx.metadata.get('duration_s', 0):.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 相关文档

- [教程: 5分钟快速入门](../tutorials/01-quick-start.md)
- [操作指南: 配置 Fallback Providers](../how-to-guides/setup-fallback-providers.md)
- [背景解释: 洋葱模型设计哲学](../explanation/onion-model-philosophy.md)
