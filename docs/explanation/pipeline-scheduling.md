# Pipeline 调度引擎详解

本文深入解释 Onion Core 的核心——**Pipeline 调度引擎**的工作原理、执行流程和关键设计决策。

## Pipeline 是什么？

Pipeline 是 Onion Core 的中央调度器，负责：
1. **编排中间件**：按优先级顺序执行请求/响应阶段的中间件
2. **调用 Provider**：执行 LLM API 调用
3. **管理重试**：指数退避重试策略
4. **处理熔断**：基于失败率的熔断器
5. **Fallback 链路**：主 Provider 失败时切换到备用 Provider

---

## 执行流程全景图

### 完整请求生命周期

```
用户调用 p.run(ctx)
    │
    ├─ 1. 输入验证（消息数、内容长度、Unicode 炸弹检测）
    │
    ├─ 2. 启动中间件链（请求阶段，正序）
    │     ├─ Tracing (priority=50)
    │     ├─ Metrics (priority=90)
    │     ├─ Observability (priority=100)
    │     ├─ RateLimit (priority=150)
    │     ├─ Safety (priority=200)
    │     └─ ContextWindow (priority=300)
    │
    ├─ 3. 调用 Provider（带重试和熔断）
    │     ├─ 检查熔断器状态
    │     ├─ 执行 provider.complete()
    │     ├─ 失败？→ 重试（指数退避）
    │     └─ 重试耗尽？→ 切换 Fallback Provider
    │
    ├─ 4. 启动中间件链（响应阶段，逆序）
    │     ├─ ContextWindow (priority=300)
    │     ├─ Safety (priority=200)
    │     ├─ RateLimit (priority=150)
    │     ├─ Observability (priority=100)
    │     ├─ Metrics (priority=90)
    │     └─ Tracing (priority=50)
    │
    └─ 5. 返回 LLMResponse
```

---

## 核心组件解析

### 1. 中间件排序机制

Pipeline 使用**优先级排序**决定中间件执行顺序：

```python
def _get_sorted_middlewares(self) -> list[BaseMiddleware]:
    if self._sorted_cache is None:
        # 按 priority 升序排序（数字越小越在外层）
        self._sorted_cache = sorted(self._middlewares, key=lambda mw: mw.priority)
    return self._sorted_cache
```

**为什么缓存排序结果？**
- 避免每次请求都重新排序（O(n log n) 开销）
- 中间件列表在运行时很少变化
- 通过 `_sorted_cache = None` 在添加新中间件时失效缓存

---

### 2. 洋葱模型的双向流动

#### 请求阶段（正序执行）

```python
# 伪代码
sorted_mws = self._get_sorted_middlewares()  # [50, 90, 100, 150, 200, 300]

for mw in sorted_mws:
    context = await mw.process_request(context)
    if context is None:
        raise MiddlewareChainAbortedError(...)
```

**关键点**：
- 每个中间件可以修改 `context` 并传递给下一个
- 如果返回 `None`，中断整个链路（`MIDDLEWARE_CHAIN_ABORTED`）
- 外层中间件先执行，内层后执行

---

#### 响应阶段（逆序执行）

```python
# 伪代码
for mw in reversed(sorted_mws):  # [300, 200, 150, 100, 90, 50]
    response = await mw.process_response(context, response)
```

**为什么逆序？**
- **对称性**：响应经过与请求相同的中间件栈
- **资源清理**：外层中间件可以在最后清理自己创建的资源
- **可观测性完整**：Tracing 在最外层，能测量完整耗时

---

### 3. 超时控制三层机制

Pipeline 实现了**三层超时保护**：

```python
async def run(self, context: AgentContext) -> LLMResponse:
    # 第 1 层：总超时（保护用户）
    if self._total_timeout:
        try:
            return await asyncio.wait_for(
                self._run_internal(context),
                timeout=self._total_timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"Total request timed out after {self._total_timeout}s")
    
    return await self._run_internal(context)
```

```python
async def _run_internal(self, context):
    # 第 2 层：中间件超时（防止单个中间件卡死）
    if self._middleware_timeout:
        response = await asyncio.wait_for(
            mw.process_request(context),
            timeout=self._middleware_timeout
        )
    
    # 第 3 层：Provider 超时（保护后端）
    if self._provider_timeout:
        response = await asyncio.wait_for(
            provider.complete(context),
            timeout=self._provider_timeout
        )
```

**超时优先级**：
1. `total_timeout` > `provider_timeout` + 所有中间件耗时
2. `provider_timeout` 独立于中间件超时
3. `middleware_timeout` 应用于每个中间件

---

### 4. 重试与指数退避

#### 重试策略分类

Pipeline 使用 `RetryPolicy` 将错误分为三类：

| 类型 | 行为 | 示例 |
|------|------|------|
| **RETRY** | 指数退避重试 | 网络抖动、临时限流 |
| **FALLBACK** | 切换到备用 Provider | 熔断器开启、配额耗尽 |
| **FATAL** | 立即抛出，不重试 | 认证失败、参数错误 |

---

#### 指数退避算法

```python
async def _call_provider_with_retry(self, provider, context):
    last_error = None
    
    for attempt in range(self._max_retries + 1):
        try:
            return await provider.complete(context)
        
        except Exception as e:
            last_error = e
            outcome = self._retry_policy.classify_error(e, context)
            
            if outcome == RetryOutcome.FATAL:
                raise  # 立即抛出
            
            if outcome == RetryOutcome.FALLBACK:
                break  # 跳出重试循环，进入 Fallback
            
            # RETRY：指数退避
            if attempt < self._max_retries:
                delay = self._retry_base_delay * (2 ** attempt)
                jitter = random.uniform(0, delay * 0.1)  # 10% 抖动
                await asyncio.sleep(delay + jitter)
    
    raise last_error
```

**退避公式**：
```
delay = base_delay × 2^attempt + jitter
```

**示例**（base_delay=0.5s）：
- 第 1 次重试：0.5s + 0~0.05s 抖动
- 第 2 次重试：1.0s + 0~0.1s 抖动
- 第 3 次重试：2.0s + 0~0.2s 抖动

---

### 5. 熔断器集成

#### 熔断器状态机

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

#### Pipeline 中的熔断器检查

```python
async def _call_provider_with_circuit_breaker(self, provider, context):
    # 获取 Provider 对应的熔断器
    cb_index = self._provider_indices[id(provider)]
    circuit_breaker = self._circuit_breakers[cb_index]
    
    # 检查熔断器状态
    if circuit_breaker.state == CircuitState.OPEN:
        raise CircuitBreakerError(
            f"Circuit breaker OPEN for {provider.name}"
        )
    
    try:
        response = await self._call_provider_with_retry(provider, context)
        circuit_breaker.record_success()  # 记录成功
        return response
    
    except Exception as e:
        circuit_breaker.record_failure()  # 记录失败
        raise
```

**关键设计**：
- 每个 Provider 有独立的熔断器
- 使用稳定索引（而非 `id()`）作为字典键，避免 GC 问题
- 熔断器状态变更不影响其他 Provider

---

### 6. Fallback Provider 链路

#### Fallback 执行逻辑

```python
async def run(self, context: AgentContext) -> LLMResponse:
    all_providers = [self._provider] + self._fallback_providers
    
    for idx, provider in enumerate(all_providers):
        try:
            return await self._call_provider_with_circuit_breaker(provider, context)
        
        except Exception as e:
            # 记录 Fallback 信息
            context.metadata["fallback_info"] = {
                "failed_provider": type(provider).__name__,
                "error": str(e),
                "switching_to": all_providers[idx + 1].name if idx + 1 < len(all_providers) else None
            }
            
            # 如果是最后一个 Provider，抛出异常
            if idx == len(all_providers) - 1:
                raise FallbackExhaustedError("All providers failed")
    
    raise RuntimeError("Unreachable")
```

**执行流程**：
1. 尝试主 Provider
2. 失败？→ 记录错误，切换到下一个
3. 尝试 Fallback 1
4. 失败？→ 继续切换
5. 所有 Provider 失败？→ 抛出 `FallbackExhaustedError`

---

## 流式响应处理

### stream() 方法特殊之处

```python
async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
    # 1. 执行请求阶段中间件（同 run()）
    context = await self._run_request_middlewares(context)
    
    # 2. 调用 Provider 流式接口
    async for chunk in provider.stream(context):
        # 3. 每个 chunk 经过中间件处理
        for mw in reversed(sorted_mws):
            chunk = await mw.process_stream_chunk(context, chunk)
        
        yield chunk
```

**关键点**：
- 请求阶段中间件只执行一次
- 每个 chunk 都要经过响应阶段中间件
- PII 脱敏在流式模式下需要缓冲（最多 2 秒或 50 字符）

---

### stream_sync() 的实现陷阱

```python
def stream_sync(self, context: AgentContext) -> Iterator[StreamChunk]:
    """同步版本的 stream()"""
    
    # ⚠️ 不能直接 yield from 异步生成器
    # 必须收集所有 chunk 到队列，然后逐个 yield
    
    loop = asyncio.new_event_loop()
    chunks_queue = queue.Queue()
    stop_event = threading.Event()
    
    def worker():
        """后台线程：运行异步 stream()"""
        async def collect_chunks():
            async for chunk in self.stream(context):
                chunks_queue.put(chunk)
            chunks_queue.put(None)  # 结束标记
        
        loop.run_until_complete(collect_chunks())
    
    thread = threading.Thread(target=worker)
    thread.start()
    
    # 主线程：从队列取 chunk 并 yield
    while True:
        chunk = chunks_queue.get(timeout=5.0)
        if chunk is None:
            break
        yield chunk
    
    thread.join(timeout=5.0)
    loop.close()
```

**为什么这么复杂？**
- Python 不允许在同步函数中直接 `yield from` 异步生成器
- 必须创建新的事件循环和后台线程
- 使用队列桥接异步和同步世界

---

## 性能优化技巧

### 1. 中间件缓存排序结果

```python
@property
def middlewares(self) -> list[BaseMiddleware]:
    return list(self._get_sorted_middlewares())  # 使用缓存
```

---

### 2. 异步 Token 计数（v0.9.3+）

tiktoken 是 CPU 密集型操作，会阻塞事件循环：

```python
# ❌ 旧实现：阻塞事件循环
token_count = tiktoken.encoding_for_model("gpt-4").encode(text)

# ✅ 新实现：卸载到线程池
loop = asyncio.get_running_loop()
token_count = await loop.run_in_executor(
    self._token_executor,  # ThreadPoolExecutor
    lambda: tiktoken.encoding_for_model("gpt-4").encode(text)
)
```

---

### 3. 连接池复用

```python
class OpenAIProvider:
    def __init__(self):
        # ✅ 全局共享连接池
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=200,
                max_keepalive_connections=20
            )
        )
```

---

## 调试技巧

### 1. 启用详细日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 查看每层中间件的耗时
# DEBUG onion_core.pipeline: Middleware X completed in 0.001s
```

---

### 2. 监控元数据

```python
response = await p.run(ctx)

print(f"总耗时: {ctx.metadata['duration_s']:.2f}s")
print(f"Provider 耗时: {ctx.metadata['provider_duration_s']:.2f}s")
print(f"Token 统计: {ctx.metadata['usage']}")
print(f"是否触发 Fallback: {'fallback_info' in ctx.metadata}")
```

---

### 3. 性能分析

```python
import cProfile

pr = cProfile.Profile()
pr.enable()

response = await p.run(ctx)

pr.disable()
pr.print_stats(sort='cumulative')
```

---

## 常见陷阱

### 陷阱 1：中间件返回 None

```python
# ❌ 错误：中间件返回 None 会中断链路
async def process_request(self, context):
    if some_condition:
        return None  # MiddlewareChainAbortedError!

# ✅ 正确：始终返回 context（可以是原对象）
async def process_request(self, context):
    if some_condition:
        return context  # 不做修改，但返回原对象
```

---

### 陷阱 2：在 async 上下文中调用 run_sync()

```python
# ❌ 错误
async def my_function():
    response = pipeline.run_sync(ctx)  # RuntimeError!

# ✅ 正确
async def my_function():
    response = await pipeline.run(ctx)
```

---

### 陷阱 3：忘记关闭 Pipeline

```python
# ❌ 错误：资源泄漏
p = Pipeline(provider=...)
response = await p.run(ctx)
# 忘记调用 shutdown()

# ✅ 正确：使用上下文管理器
async with Pipeline(provider=...) as p:
    response = await p.run(ctx)
# 自动调用 shutdown()
```

---

## 总结

Pipeline 调度引擎是 Onion Core 的核心，它通过：
- ✅ **洋葱模型**：双向流动的中间件链
- ✅ **三层超时**：总超时、中间件超时、Provider 超时
- ✅ **智能重试**：指数退避 + 错误分类
- ✅ **熔断保护**：防止雪崩效应
- ✅ **Fallback 链路**：提高可用性

理解这些机制，可以帮助你更好地配置和优化 Pipeline。

---

## 延伸阅读

- [API 参考: Pipeline](../reference/pipeline.md)
- [操作指南: 解决超时问题](../how-to-guides/troubleshoot-timeouts.md)
- [背景解释: 洋葱模型设计哲学](onion-model-philosophy.md)
