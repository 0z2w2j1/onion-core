# 多 Provider 故障转移教程

在本教程中，你将学习如何配置多个 LLM Provider，实现自动故障转移，提高系统可用性。

## 前提条件

- 已完成 [5分钟快速入门](01-quick-start.md)
- 拥有至少 2 个 Provider 的 API Key（如 OpenAI、DeepSeek、智谱等）

## 为什么需要 Fallback？

生产环境中，单个 Provider 可能因以下原因不可用：
- API 限流或配额耗尽
- 服务中断或维护
- 网络问题或超时

通过配置 Fallback Providers，当主 Provider 失败时，系统会自动切换到备用 Provider，确保服务持续可用。

---

## 第 1 步：准备多个 Provider

```python
from onion_core.providers import (
    OpenAIProvider,
    DeepSeekProvider,
    ZhipuAIProvider,
)

# 主 Provider: OpenAI GPT-4
primary = OpenAIProvider(
    api_key="sk-openai-...",
    model="gpt-4-turbo",
)

# 备用 Provider 1: DeepSeek（性价比高）
fallback_1 = DeepSeekProvider(
    api_key="sk-deepseek-...",
    model="deepseek-chat",
)

# 备用 Provider 2: 智谱 GLM-4（国内访问快）
fallback_2 = ZhipuAIProvider(
    api_key="zhipu-...",
    model="glm-4",
)
```

**选择 Provider 的原则**：
- ✅ **多样性**：不同厂商，避免单点故障
- ✅ **成本梯度**：从便宜到昂贵排序
- ✅ **地域分布**：国内外 Provider 搭配

---

## 第 2 步：创建带 Fallback 的 Pipeline

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message
from onion_core.middlewares import ObservabilityMiddleware

async def main():
    async with Pipeline(
        provider=primary,                    # 主 Provider
        fallback_providers=[fallback_1, fallback_2],  # 备用 Provider 列表
        max_retries=2,                       # 每个 Provider 重试 2 次
        enable_circuit_breaker=True,         # 启用熔断器
        circuit_failure_threshold=3,         # 连续 3 次失败后熔断
    ) as p:
        p.add_middleware(ObservabilityMiddleware())
        
        # 执行请求
        ctx = AgentContext(messages=[
            Message(role="user", content="解释量子计算")
        ])
        
        response = await p.run(ctx)
        print(f"回复: {response.content[:100]}...")
        
        # 检查是否触发了 Fallback
        if "fallback_info" in ctx.metadata:
            info = ctx.metadata["fallback_info"]
            print(f"⚠️  主 Provider 失败，使用了 {info['used_provider']}")
        else:
            print("✅ 主 Provider 成功响应")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 第 3 步：测试故障转移

### 模拟主 Provider 失败

```python
async def test_fallback():
    # 使用无效的 API Key 模拟认证失败
    bad_primary = OpenAIProvider(
        api_key="sk-invalid-key",
        model="gpt-4",
    )
    
    async with Pipeline(
        provider=bad_primary,
        fallback_providers=[fallback_1],
        max_retries=1,
    ) as p:
        ctx = AgentContext(messages=[
            Message(role="user", content="你好")
        ])
        
        try:
            response = await p.run(ctx)
            print(f"✅ Fallback 成功: {response.content}")
            print(f"📊 使用的 Provider: {ctx.metadata.get('provider_name')}")
        
        except Exception as e:
            print(f"❌ 所有 Provider 失败: {e}")

asyncio.run(test_fallback())
```

**预期输出**：
```
[WARNING] Primary provider failed: Invalid API key
[INFO] Switching to fallback provider: DeepSeekProvider#1
✅ Fallback 成功: Echo: 你好
📊 使用的 Provider: DeepSeekProvider#1
```

---

## 第 4 步：监控 Fallback 使用情况

### 记录 Fallback 统计

```python
class FallbackTracker:
    def __init__(self):
        self.fallback_count = 0
        self.total_requests = 0
    
    def record(self, context: AgentContext):
        self.total_requests += 1
        if "fallback_info" in context.metadata:
            self.fallback_count += 1
            provider = context.metadata["fallback_info"]["used_provider"]
            print(f"⚠️  Fallback 触发: {provider}")
    
    def get_stats(self):
        rate = self.fallback_count / max(self.total_requests, 1) * 100
        return f"Fallback 率: {self.fallback_count}/{self.total_requests} ({rate:.1f}%)"

# 使用
tracker = FallbackTracker()

async def monitored_request():
    async with Pipeline(...) as p:
        response = await p.run(ctx)
        tracker.record(ctx)
        return response

# 运行一段时间后查看统计
print(tracker.get_stats())
# 输出: Fallback 率: 5/100 (5.0%)
```

---

## 第 5 步：成本优化策略

### 按价格排序 Provider

```python
# 成本从低到高（每 1M tokens）
cheap = DeepSeekProvider(api_key="...")      # $0.14
mid = ZhipuAIProvider(api_key="...")         # $0.28
expensive = OpenAIProvider(api_key="...")    # $10.00

# 优先使用便宜的，失败后再用贵的
async with Pipeline(
    provider=cheap,
    fallback_providers=[mid, expensive],
) as p:
    ...
```

**好处**：
- ✅ 大部分请求使用便宜 Provider
- ✅ 只在必要时切换到昂贵 Provider
- ✅ 平衡成本和可用性

---

### 根据场景选择 Provider

```python
def select_providers(task_type: str):
    """根据任务类型选择合适的 Provider 组合"""
    
    if task_type == "creative_writing":
        # 创意写作：优先质量
        primary = OpenAIProvider(model="gpt-4")
        fallbacks = [DeepSeekProvider()]
    
    elif task_type == "code_generation":
        # 代码生成：Claude 擅长代码
        from onion_core.providers import AnthropicProvider
        primary = AnthropicProvider(model="claude-3-opus")
        fallbacks = [OpenAIProvider(model="gpt-4")]
    
    else:
        # 通用任务：性价比优先
        primary = DeepSeekProvider()
        fallbacks = [ZhipuAIProvider()]
    
    return primary, fallbacks

# 使用
primary, fallbacks = select_providers("code_generation")
async with Pipeline(provider=primary, fallback_providers=fallbacks) as p:
    ...
```

---

## 第 6 步：健康检查与主动切换

### 定期检测 Provider 健康状态

```python
import asyncio

class HealthAwarePipeline:
    def __init__(self, providers: list):
        self.providers = providers
        self.health_status = {i: True for i in range(len(providers))}
    
    async def check_health(self, idx: int) -> bool:
        """简单健康检查：发送测试请求"""
        try:
            provider = self.providers[idx]
            test_ctx = AgentContext(messages=[
                Message(role="user", content="Hi")
            ])
            await provider.complete(test_ctx)
            return True
        except Exception:
            return False
    
    async def get_healthy_provider(self) -> int:
        """获取第一个健康的 Provider"""
        for idx in range(len(self.providers)):
            if self.health_status[idx]:
                is_healthy = await self.check_health(idx)
                if is_healthy:
                    return idx
                else:
                    self.health_status[idx] = False
                    print(f"⚠️  Provider {idx} 不健康，标记为故障")
        return 0  # 默认使用第一个
    
    async def run(self, context: AgentContext):
        idx = await self.get_healthy_provider()
        pipeline = Pipeline(provider=self.providers[idx])
        return await pipeline.run(context)

# 使用
providers = [primary, fallback_1, fallback_2]
health_pipeline = HealthAwarePipeline(providers)

# 后台定期健康检查
async def health_check_loop():
    while True:
        for idx in range(len(providers)):
            is_healthy = await health_pipeline.check_health(idx)
            health_pipeline.health_status[idx] = is_healthy
        await asyncio.sleep(60)  # 每分钟检查一次

asyncio.create_task(health_check_loop())
```

---

## 完整示例：生产级 Fallback 配置

```python
import asyncio
import logging
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider, DeepSeekProvider, ZhipuAIProvider
from onion_core.middlewares import ObservabilityMiddleware

logging.basicConfig(level=logging.INFO)

async def main():
    # 三级 Provider 链路
    primary = OpenAIProvider(
        api_key="sk-openai-...",
        model="gpt-4-turbo",
    )
    fallback_1 = DeepSeekProvider(
        api_key="sk-deepseek-...",
        model="deepseek-chat",
    )
    fallback_2 = ZhipuAIProvider(
        api_key="zhipu-...",
        model="glm-4",
    )
    
    async with Pipeline(
        provider=primary,
        fallback_providers=[fallback_1, fallback_2],
        max_retries=2,
        provider_timeout=30.0,
        total_timeout=90.0,  # 总超时 = 3 个 Provider × 30s
        enable_circuit_breaker=True,
        circuit_failure_threshold=3,
        circuit_recovery_timeout=60.0,
    ) as p:
        p.add_middleware(ObservabilityMiddleware())
        
        ctx = AgentContext(messages=[
            Message(role="user", content="解释量子纠缠")
        ])
        
        try:
            response = await p.run(ctx)
            print(f"✅ 成功")
            print(f"📊 Provider: {ctx.metadata.get('provider_name')}")
            print(f"⏱️  耗时: {ctx.metadata.get('duration_s', 0):.2f}s")
            
            if "fallback_info" in ctx.metadata:
                info = ctx.metadata["fallback_info"]
                print(f"⚠️  Fallback: {info['used_provider']}")
        
        except Exception as e:
            print(f"❌ 所有 Provider 失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 你学到了什么

✅ 如何配置多个 Provider 实现故障转移  
✅ 如何监控 Fallback 使用情况  
✅ 如何按成本和场景优化 Provider 选择  
✅ 如何实现健康检查和主动切换  

## 常见陷阱

### 陷阱 1：Fallback 链太长

```python
# ❌ 错误：太多 Fallback，延迟高
fallbacks = [fb1, fb2, fb3, fb4, fb5]

# ✅ 正确：最多 2-3 个 Fallback
fallbacks = [fb1, fb2]
```

---

### 陷阱 2：忘记启用熔断器

```python
# ❌ 错误：没有熔断器，持续调用失败的 Provider
pipeline = Pipeline(provider=primary, fallback_providers=[fallback_1])

# ✅ 正确：启用熔断器
pipeline = Pipeline(
    provider=primary,
    fallback_providers=[fallback_1],
    enable_circuit_breaker=True,
)
```

---

## 下一步

- 查看 **[操作指南: 设置 Fallback Providers](../how-to-guides/setup-fallback-providers.md)** 了解更多高级配置
- 阅读 **[背景解释: 错误码系统](../explanation/error-code-system.md)** 理解重试策略
- 继续学习 **[流式响应与同步 API](04-streaming-sync.md)**
