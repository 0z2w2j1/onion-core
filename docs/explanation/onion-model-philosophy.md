# 洋葱模型设计哲学

本文解释为什么 Onion Core 选择**洋葱模型（Onion Architecture）**作为其中间件架构，以及这种设计带来的优势与权衡。

## 什么是洋葱模型？

洋葱模型是一种分层架构模式，其中每一层都包裹着核心业务逻辑。在 Onion Core 中，LLM Provider 调用位于最内层，而各种中间件（安全、限流、监控等）像洋葱皮一样层层包裹。

```
        用户请求
             │
             ▼
    ┌─────────────────┐
    │ [1] Tracing     │ ◄── 最外层（priority=50）
    │ [2] Metrics     │
    │ [3] Observ.     │
    │ [4] Rate Limit  │
    │ [5] Safety      │
    │ [6] Context     │ ◄── 最内层（priority=300）
    └────────┬────────┘
             │
             ▼
       [ LLM Provider ]
             │
             ▼
    ┌────────┴────────┐
    │ [6] Context     │ ◄── 响应阶段逆序执行
    │ [5] Safety      │
    │ [4] Rate Limit  │
    │ [3] Observ.     │
    │ [2] Metrics     │
    │ [1] Tracing     │
    └─────────────────┘
```

## 为什么不是传统中间件链？

### 传统 Express/Koa 风格的中间件链

```python
# 传统方式：线性执行
async def middleware_chain(request):
    result = await mw1(request)
    result = await mw2(result)
    result = await mw3(result)
    return result
```

**问题**：
1. **响应处理困难**：难以在响应返回时执行逆向操作（如清理资源、计算总耗时）
2. **错误恢复复杂**：某层失败后，难以通知外层中间件进行补偿操作
3. **上下文传递混乱**：需要在每层之间手动传递状态

### 洋葱模型的优势

```python
# 洋葱模型：双向流动
async def onion_model(context):
    # 请求阶段（正序）
    context = await mw1.process_request(context)
    context = await mw2.process_request(context)
    
    # 核心调用
    response = await provider.complete(context)
    
    # 响应阶段（逆序）
    response = await mw2.process_response(context, response)
    response = await mw1.process_response(context, response)
    return response
```

**优势**：
1. ✅ **对称性**：请求和响应经过相同的中间件栈，便于审计和调试
2. ✅ **资源管理**：外层中间件可以在响应阶段清理自己在请求阶段创建的资源
3. ✅ **可观测性完整**：Tracing 中间件可以包裹整个调用链，准确测量端到端延迟
4. ✅ **故障隔离**：内层失败时，外层中间件的 `on_error()` 钩子会被调用，允许优雅降级

## 优先级排序的设计决策

### 为什么 Tracing 在最外层（priority=50）？

```
Tracing (50) → Metrics (90) → Safety (200) → Context (300) → [LLM]
```

**原因**：
- Tracing 需要测量**完整**的请求生命周期，包括其他中间件的执行时间
- 如果 Tracing 在内层，将无法捕获外层中间件的延迟

### 为什么 Safety 在 Context 之前？

```
Safety (200) → Context (300) → [LLM]
```

**原因**：
- **安全优先原则**：应该在裁剪上下文之前检测并拦截恶意输入
- 如果先裁剪，攻击者可能通过超长 payload 绕过关键词检测

### 为什么 Rate Limit 在 Safety 之后？

```
Rate Limit (150) → Safety (200)
```

**原因**：
- 限流是**廉价**操作（内存查找），应该尽早拒绝过量请求以保护后端
- 但 Safety 更关键，所以优先级更高（数字更大表示更靠近核心）

> **注意**：priority 数字**越小**越在外层，**越大**越在内层。

## 洋葱模型的权衡

### 优点

| 优点 | 说明 |
|------|------|
| **清晰的职责分离** | 每层只关心自己的逻辑 |
| **易于测试** | 可以单独测试每个中间件 |
| **可组合性** | 可以动态添加/移除中间件 |
| **可观测性强** | 外层可以监控内层的执行情况 |

### 缺点

| 缺点 | 缓解措施 |
|------|----------|
| **延迟累积** | 每层增加少量延迟，多层叠加可能显著 | 使用 `middleware_timeout` 限制单层最大耗时 |
| **调试复杂** | 错误可能在任何一层被拦截或修改 | 结构化日志记录每层的输入输出 |
| **顺序敏感** | 错误的中间件顺序可能导致功能异常 | 文档明确推荐顺序，提供 `from_config()` 自动配置 |

## 实际案例：PII 脱敏的洋葱路径

假设用户发送："我的电话是 13812345678"

1. **Tracing (50)**: 创建 span，记录 `request_id`
2. **Metrics (90)**: 递增 `onion_requests_total` 计数器
3. **Safety (200)**: 
   - 请求阶段：检测无注入攻击，通过
   - 响应阶段：脱敏输出 "我的电话是 ***"
4. **Context (300)**: 计算 Token 数，检查是否超限
5. **[LLM]**: 生成回复
6. **Context (300)**: 记录裁剪后的 Token 统计
7. **Safety (200)**: 执行 PII 脱敏
8. **Metrics (90)**: 记录响应延迟
9. **Tracing (50)**: 关闭 span，上报追踪数据

如果没有洋葱模型，PII 脱敏可能无法在正确的时机执行。

## 与其他框架的对比

| 框架 | 架构模式 | 特点 |
|------|----------|------|
| **Onion Core** | 洋葱模型 | 双向流动，对称处理 |
| **Express.js** | 线性链 | 单向流动，响应处理弱 |
| **Django Middleware** | 洋葱模型 | 类似，但同步阻塞 |
| **FastAPI Dependencies** | 依赖注入 | 更细粒度，但复杂度更高 |

## 总结

洋葱模型是 Onion Core 的核心设计决策，它通过**对称的请求-响应处理**和**清晰的层次划分**，实现了生产级 AI 应用所需的安全性、可观测性和可靠性。

虽然引入了少量复杂性，但通过严格的优先级规则和结构化日志，这种复杂性是可管理的。

## 延伸阅读

- [Pipeline 调度引擎详解](pipeline-scheduling.md) - 了解洋葱模型的具体实现
- [错误码系统设计](error-code-system.md) - 各层如何协同处理错误
- [性能基准测试解读](benchmark-interpretation.md) - 洋葱模型对延迟的影响
