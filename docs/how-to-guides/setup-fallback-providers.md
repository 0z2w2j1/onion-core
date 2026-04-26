# 如何设置多 Provider 故障转移

本指南展示如何配置主备 Provider 链路，当主 Provider 失败时自动切换到备用 Provider。

## 前提条件

- 已了解 [5分钟快速入门](../tutorials/01-quick-start.md)
- 拥有多个 Provider 的 API Key（如 OpenAI、DeepSeek、智谱等）

## 为什么需要 Fallback Providers？

生产环境中，单个 LLM Provider 可能因以下原因不可用：
- API 限流或配额耗尽
- 服务中断或维护
- 网络问题或超时
- 模型暂时不可用

通过配置 Fallback Providers，可以显著提高系统可用性。

---

## 基本配置

### 步骤 1: 准备多个 Provider

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

# 备用 Provider 1: DeepSeek
fallback_1 = DeepSeekProvider(
    api_key="sk-deepseek-...",
    model="deepseek-chat",
)

# 备用 Provider 2: 智谱 GLM-4
fallback_2 = ZhipuAIProvider(
    api_key="zhipu-...",
    model="glm-4",
)
```

---

### 步骤 2: 创建带 Fallback 的 Pipeline

```python
from onion_core import Pipeline

async with Pipeline(
    provider=primary,
    fallback_providers=[fallback_1, fallback_2],
    max_retries=2,              # 每个 Provider 重试 2 次
    enable_circuit_breaker=True, # 启用熔断器
) as p:
    p.add_middleware(ObservabilityMiddleware())
    
    # 执行请求
    ctx = AgentContext(messages=[...])
    response = await p.run(ctx)
```

**执行流程**:
```
1. 尝试 primary (OpenAI)
   ├─ 成功 → 返回结果
   └─ 失败 → 重试 2 次
       └─ 仍失败 → 切换到 fallback_1

2. 尝试 fallback_1 (DeepSeek)
   ├─ 成功 → 返回结果
   └─ 失败 → 重试 2 次
       └─ 仍失败 → 切换到 fallback_2

3. 尝试 fallback_2 (ZhipuAI)
   ├─ 成功 → 返回结果
   └─ 失败 → 抛出异常（所有 Provider 耗尽）
```

---

## 高级配置

### 1. 自定义重试策略

不同错误类型采用不同的重试行为：

```python
from onion_core.models import RetryPolicy, RetryOutcome
from onion_core.error_codes import ErrorCode

class CustomRetryPolicy(RetryPolicy):
    def classify_error(self, error: Exception, context) -> RetryOutcome:
        # 认证错误：不重试，直接切换 Provider
        if hasattr(error, 'error_code') and error.error_code == ErrorCode.PROVIDER_AUTH_FAILED:
            return RetryOutcome.FALLBACK
        
        # 限流错误：指数退避重试
        if hasattr(error, 'error_code') and error.error_code == ErrorCode.RATE_LIMIT_EXCEEDED:
            return RetryOutcome.RETRY
        
        # 内容过滤错误：不重试
        if hasattr(error, 'error_code') and error.error_code == ErrorCode.PROVIDER_CONTENT_FILTER:
            return RetryOutcome.FATAL
        
        # 默认：重试
        return super().classify_error(error, context)

async with Pipeline(
    provider=primary,
    fallback_providers=[fallback_1],
    retry_policy=CustomRetryPolicy(),
    max_retries=3,
) as p:
    ...
```

---

### 2. 监控 Fallback 触发

在元数据中记录 Fallback 使用情况：

```python
async def run_with_fallback_tracking():
    async with Pipeline(
        provider=primary,
        fallback_providers=[fallback_1, fallback_2],
    ) as p:
        p.add_middleware(ObservabilityMiddleware())
        
        ctx = AgentContext(messages=[...])
        response = await p.run(ctx)
        
        # 检查是否触发了 Fallback
        fallback_info = ctx.metadata.get("fallback_info")
        if fallback_info:
            print(f"⚠️ 主 Provider 失败，使用了 {fallback_info['used_provider']}")
            print(f"   失败原因: {fallback_info['primary_error']}")
            print(f"   切换次数: {fallback_info['switch_count']}")
        else:
            print("✅ 主 Provider 成功响应")
```

**元数据结构**:
```python
{
    "fallback_info": {
        "used_provider": "DeepSeekProvider#1",
        "primary_error": "TimeoutError: Request timed out after 30s",
        "switch_count": 1,
        "attempted_providers": ["OpenAIProvider#0", "DeepSeekProvider#1"],
    }
}
```

---

### 3. 健康检查与主动切换

定期检查 Provider 健康状况，提前切换：

```python
import asyncio

class HealthAwarePipeline:
    def __init__(self, providers: list):
        self.providers = providers
        self.health_status = {i: True for i in range(len(providers))}
    
    async def check_health(self, provider_idx: int) -> bool:
        """简单健康检查：发送测试请求"""
        try:
            provider = self.providers[provider_idx]
            test_ctx = AgentContext(messages=[
                Message(role="user", content="Hi")
            ])
            await provider.complete(test_ctx)
            return True
        except Exception:
            return False
    
    async def get_healthy_provider(self) -> int:
        """获取第一个健康的 Provider 索引"""
        for idx in range(len(self.providers)):
            if self.health_status[idx]:
                is_healthy = await self.check_health(idx)
                if is_healthy:
                    return idx
                else:
                    self.health_status[idx] = False
        return 0  # 默认使用第一个
    
    async def run(self, context: AgentContext):
        idx = await self.get_healthy_provider()
        pipeline = Pipeline(provider=self.providers[idx])
        return await pipeline.run(context)

# 使用
providers = [primary, fallback_1, fallback_2]
health_pipeline = HealthAwarePipeline(providers)
response = await health_pipeline.run(ctx)
```

---

## 成本优化策略

### 按优先级和成本排序

将便宜的 Provider 作为主要选择，贵的作为备用：

```python
# 成本从低到高排序
cheap_primary = DeepSeekProvider(api_key="...")      # $0.14 / 1M tokens
mid_fallback = ZhipuAIProvider(api_key="...")        # $0.28 / 1M tokens
expensive_fallback = OpenAIProvider(api_key="...")   # $10.00 / 1M tokens

async with Pipeline(
    provider=cheap_primary,
    fallback_providers=[mid_fallback, expensive_fallback],
) as p:
    ...
```

---

### 根据场景选择 Provider

```python
def select_provider_for_task(task_type: str):
    """根据任务类型选择合适的 Provider"""
    if task_type == "creative_writing":
        # 创意写作：优先使用 GPT-4
        return OpenAIProvider(model="gpt-4"), [DeepSeekProvider()]
    elif task_type == "code_generation":
        # 代码生成：优先使用 Claude
        from onion_core.providers import AnthropicProvider
        return AnthropicProvider(model="claude-3-opus"), [OpenAIProvider(model="gpt-4")]
    else:
        # 通用任务：使用性价比高的 DeepSeek
        return DeepSeekProvider(), [ZhipuAIProvider()]

# 使用
provider, fallbacks = select_provider_for_task("code_generation")
async with Pipeline(provider=provider, fallback_providers=fallbacks) as p:
    ...
```

---

## 故障排查

### Q: Fallback 没有触发？

A: 检查以下几点：
1. 确认 `max_retries` 设置合理（至少 1 次）
2. 查看日志中的错误码，确认不是 `FATAL` 类型
3. 验证备用 Provider 配置正确（API Key、base_url 等）

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

### Q: 如何跳过某个 Fallback？

A: 在运行时动态移除：

```python
async def run_without_fallback_1():
    # 临时移除 fallback_1
    active_fallbacks = [fb for fb in [fallback_1, fallback_2] if fb != fallback_1]
    
    async with Pipeline(
        provider=primary,
        fallback_providers=active_fallbacks,
    ) as p:
        return await p.run(ctx)
```

---

### Q: 如何统计各 Provider 的使用比例？

A: 使用中间件记录：

```python
from onion_core.middlewares import BaseMiddleware

class ProviderUsageTracker(BaseMiddleware):
    def __init__(self):
        super().__init__(name="provider_tracker", priority=95)
        self.usage_count = {}
    
    async def process_response(self, context, response):
        provider_name = context.metadata.get("provider_name", "unknown")
        self.usage_count[provider_name] = self.usage_count.get(provider_name, 0) + 1
        return response
    
    def get_stats(self):
        total = sum(self.usage_count.values())
        return {
            name: f"{count}/{total} ({count/total*100:.1f}%)"
            for name, count in self.usage_count.items()
        }

# 使用
tracker = ProviderUsageTracker()
p.add_middleware(tracker)

# 运行一段时间后查看统计
print(tracker.get_stats())
# 输出: {'OpenAIProvider#0': '80/100 (80.0%)', 'DeepSeekProvider#1': '20/100 (20.0%)'}
```

---

## 最佳实践

1. ✅ **至少配置 2 个 Provider**：避免单点故障
2. ✅ **启用熔断器**：防止持续调用失败的 Provider
3. ✅ **监控 Fallback 触发率**：如果频繁切换，说明主 Provider 不稳定
4. ✅ **定期健康检查**：主动检测 Provider 可用性
5. ❌ **不要过度依赖 Fallback**：频繁切换会增加延迟和成本
6. ❌ **避免循环依赖**：不要在 Fallback 中使用相同的 API Key

---

## 完整示例

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider, DeepSeekProvider, ZhipuAIProvider
from onion_core.middlewares import ObservabilityMiddleware

async def main():
    # 配置三级 Provider 链路
    primary = OpenAIProvider(api_key="sk-openai-...", model="gpt-4-turbo")
    fallback_1 = DeepSeekProvider(api_key="sk-deepseek-...", model="deepseek-chat")
    fallback_2 = ZhipuAIProvider(api_key="zhipu-...", model="glm-4")
    
    async with Pipeline(
        provider=primary,
        fallback_providers=[fallback_1, fallback_2],
        max_retries=2,
        provider_timeout=30.0,
        enable_circuit_breaker=True,
        circuit_failure_threshold=3,
    ) as p:
        p.add_middleware(ObservabilityMiddleware())
        
        ctx = AgentContext(messages=[
            Message(role="user", content="解释量子纠缠")
        ])
        
        try:
            response = await p.run(ctx)
            print(f"✅ 回复: {response.content[:100]}...")
            print(f"📊 Provider: {ctx.metadata.get('provider_name')}")
            print(f"⏱️  耗时: {ctx.metadata.get('duration_s', 0):.2f}s")
            
            # 检查是否触发了 Fallback
            if "fallback_info" in ctx.metadata:
                info = ctx.metadata["fallback_info"]
                print(f"⚠️  Fallback 触发: {info['used_provider']}")
        
        except Exception as e:
            print(f"❌ 所有 Provider 失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 下一步

- 查看 **[API 参考: Pipeline](../reference/pipeline.md)** 了解完整参数
- 阅读 **[背景解释: 降级策略](../explanation/degradation-strategy.md)** 理解重试和熔断原理
- 学习 **[操作指南: 解决超时问题](troubleshoot-timeouts.md)** 优化响应速度
