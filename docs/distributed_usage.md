# 分布式能力使用指南

> **版本**: v1.0.0+ | **适用场景**: 多实例部署、Kubernetes 集群、高可用架构

## 概述

Onion Core 提供完整的分布式中间件支持，使您的 AI Agent 应用能够水平扩展至多个实例，同时保持共享状态和一致性。

### 核心特性

- ✅ **分布式限流**：多实例共享限流状态，防止工具调用风暴
- ✅ **分布式缓存**：跨实例共享 LLM 响应缓存，降低成本
- ✅ **分布式熔断器**：全局服务健康度感知，支持 CLOSED → OPEN → HALF_OPEN 状态转换
- ✅ **配置中心集成**：通过环境变量和 Redis 后端实现动态配置

---

## 前置要求

### 安装 Redis 依赖

```bash
pip install "onion-core[redis]"
# 或
pip install redis>=5.0
```

### Redis 配置建议

```conf
# redis.conf

# 内存限制（根据缓存大小调整）
maxmemory 2gb

# LRU 淘汰策略（必需）
maxmemory-policy allkeys-lru

# 持久化（可选，推荐 RDB）
save 900 1
save 300 10
save 60 10000

# 连接超时
timeout 300
tcp-keepalive 60
```

---

## 1. 分布式限流（DistributedRateLimitMiddleware）

### 基础用法

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message, EchoProvider
from onion_core.middlewares import DistributedRateLimitMiddleware

async def main():
    # 创建分布式限流中间件
    rate_limiter = DistributedRateLimitMiddleware(
        redis_url="redis://localhost:6379",
        max_requests=60,          # 每分钟最多 60 次普通请求
        window_seconds=60.0,
        max_tool_calls=30,        # 每分钟最多 30 次工具调用
        tool_call_window=60.0,
        pool_size=10,             # Redis 连接池大小
        fallback_allow=False,     # Redis 故障时拒绝请求（更安全）
    )
    
    async with Pipeline(provider=EchoProvider()) as p:
        p.add_middleware(rate_limiter)
        
        ctx = AgentContext(
            session_id="user-123",
            messages=[Message(role="user", content="Hello")]
        )
        
        try:
            response = await p.run(ctx)
            print(f"Remaining quota: {ctx.metadata.get('rate_limit_remaining')}")
        except Exception as e:
            print(f"Rate limited: {e}")

asyncio.run(main())
```

### 分层限流配置示例

```python
# 场景：允许高频对话，但严格限制工具调用（防止 API 成本爆炸）
rate_limiter = DistributedRateLimitMiddleware(
    redis_url="redis://my-redis-cluster:6379",
    
    # 普通对话：宽松限制
    max_requests=120,       # 每分钟 120 次
    window_seconds=60.0,
    
    # 工具调用：严格限制
    max_tool_calls=20,      # 每分钟仅 20 次
    tool_call_window=60.0,
    
    key_prefix="onion:prod:ratelimit",  # 生产环境隔离
    fallback_allow=False,               # 安全优先
)
```

### 监控限流状态

```python
# 查询用户限流使用情况
usage = await rate_limiter.get_usage("user-123")
print(usage)
# 输出：
# {
#     "session_id": "user-123",
#     "requests_in_window": 45,
#     "max_requests": 60,
#     "request_remaining": 15,
#     "tool_calls_in_window": 8,
#     "max_tool_calls": 30,
#     "tool_call_remaining": 22,
#     "window_seconds": 60.0,
#     "tool_call_window_seconds": 60.0,
#     "distributed": True
# }

# 重置用户限流（客服场景）
await rate_limiter.reset_session("user-123")

# 紧急情况下清除所有限流（谨慎使用）
# await rate_limiter.reset_all()
```

### Kubernetes 多实例部署

```yaml
# kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: onion-core-agent
spec:
  replicas: 3  # 3 个实例共享 Redis 限流状态
  template:
    spec:
      containers:
      - name: agent
        image: onion-core:1.0.0
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: MAX_REQUESTS
          value: "180"  # 3 实例总计 180 req/min = 每实例 60 req/min
```

---

## 2. 分布式缓存（DistributedCacheMiddleware）

### 基础用法

```python
from onion_core.middlewares import DistributedCacheMiddleware

async def main():
    # 创建分布式缓存中间件
    cache = DistributedCacheMiddleware(
        redis_url="redis://localhost:6379/1",  # 使用 database 1 隔离
        ttl_seconds=300,         # 缓存 5 分钟
        max_size=1000,           # 最大 1000 条目（由 Redis maxmemory 控制）
        key_prefix="onion:cache",
        pool_size=20,
        cache_key_strategy="full",  # 完整消息 + 配置作为缓存键
    )
    
    async with Pipeline(provider=MyOpenAIProvider()) as p:
        p.add_middleware(cache)
        
        # 第一次请求：缓存未命中，调用 LLM
        ctx1 = AgentContext(messages=[Message(role="user", content="什么是 Python?")])
        resp1 = await p.run(ctx1)
        print(f"Cache hits: {cache.hits}, misses: {cache.misses}")
        # 输出: Cache hits: 0, misses: 1
        
        # 第二次相同请求：缓存命中，直接返回
        ctx2 = AgentContext(messages=[Message(role="user", content="什么是 Python?")])
        resp2 = await p.run(ctx2)
        print(f"Cache hits: {cache.hits}, misses: {cache.misses}")
        # 输出: Cache hits: 1, misses: 1
        print(f"Hit rate: {cache.hit_rate:.1%}")
        # 输出: Hit rate: 50.0%

asyncio.run(main())
```

### 缓存策略选择

```python
# 策略 1：完整上下文缓存（默认，最准确）
cache = DistributedCacheMiddleware(
    cache_key_strategy="full",  # 包含所有消息 + temperature/max_tokens 等配置
)

# 策略 2：仅用户消息缓存（适合 FAQ 场景）
cache = DistributedCacheMiddleware(
    cache_key_strategy="user_only",  # 忽略系统提示和历史对话
)

# 策略 3：自定义缓存键（高级用法）
class CustomCacheMiddleware(DistributedCacheMiddleware):
    def _generate_cache_key(self, context: AgentContext) -> str:
        # 仅基于用户意图生成缓存键（需配合意图识别模型）
        intent = extract_intent(context.messages[-1].content)
        return hashlib.md5(intent.encode()).hexdigest()
```

### 缓存管理

```python
# 查看缓存大小
size = await cache.get_cache_size()
print(f"Current cache size: {size} entries")

# 清空缓存（部署新版本时）
await cache.clear_cache()

# 监控缓存性能
print(f"Hit rate: {cache.hit_rate:.1%}")
print(f"Total hits: {cache.hits}, misses: {cache.misses}")
```

### 成本优化示例

```python
# 场景：FAQ 机器人，大量重复问题
cache = DistributedCacheMiddleware(
    redis_url="redis://cache-cluster:6379",
    ttl_seconds=3600,       # 缓存 1 小时（FAQ 答案不常变）
    max_size=10000,         # 容纳 10k 常见问题
    cache_key_strategy="user_only",  # 仅匹配用户问题
)

# 预期效果：
# - 缓存命中率：60-80%
# - LLM 调用减少：60-80%
# - 响应延迟降低：从 500ms → 5ms
# - 成本节省：$1000/月 → $200/月
```

---

## 3. 分布式熔断器（DistributedCircuitBreakerMiddleware）

### 基础用法

```python
from onion_core.middlewares import DistributedCircuitBreakerMiddleware

async def main():
    circuit_breaker = DistributedCircuitBreakerMiddleware(
        redis_url="redis://localhost:6379/2",
        failure_threshold=5,         # 连续失败 5 次触发熔断
        recovery_timeout=30.0,       # 熔断 30 秒后进入半开状态
        success_threshold=2,         # 半开状态连续成功 2 次恢复
        key_prefix="onion:prod:cb",
        pool_size=10,
    )

    async with Pipeline(provider=EchoProvider()) as p:
        p.add_middleware(circuit_breaker)

        ctx = AgentContext(
            session_id="user-123",
            messages=[Message(role="user", content="Hello")]
        )

        try:
            response = await p.run(ctx)
            print(response.content)
        except Exception as e:
            print(f"Circuit breaker blocked: {e}")

asyncio.run(main())
```

### 状态查询

```python
# 查询 Provider 熔断状态
state = await circuit_breaker.get_state("OpenAIProvider")
print(state)
# 输出：
# {
#     "provider": "OpenAIProvider",
#     "state": "CLOSED",          # CLOSED / OPEN / HALF_OPEN
#     "failure_count": 0,
#     "success_count": 0,
#     "last_failure_time": None,
# }

# 手动重置熔断器
await circuit_breaker.reset("OpenAIProvider")
```

### 与 Pipeline 原生熔断的对比

Pipeline 内置的 `enable_circuit_breaker=True` 使用进程内内存状态，适合单实例部署。`DistributedCircuitBreakerMiddleware` 通过 Redis 共享状态，适合多实例部署，确保所有实例对同一 Provider 的健康状态有一致认知。

---

## 4. 组合使用：完整生产配置

```python
"""
生产环境 Pipeline 配置示例
- 分布式限流：防止滥用
- 分布式缓存：降低成本
- 安全护栏：PII 脱敏
- 上下文管理：Token 控制
"""

from onion_core import Pipeline, AgentContext
from onion_core.providers import OpenAIProvider
from onion_core.middlewares import (
    DistributedRateLimitMiddleware,
    DistributedCacheMiddleware,
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
    ObservabilityMiddleware,
)

async def create_production_pipeline():
    provider = OpenAIProvider(
        api_key="sk-...",
        model="gpt-4o",
    )
    
    async with Pipeline(
        provider=provider,
        max_retries=3,
        enable_circuit_breaker=True,
    ) as p:
        # 1. 可观测性（最外层）
        p.add_middleware(ObservabilityMiddleware())
        
        # 2. 分布式缓存（priority=75）
        p.add_middleware(DistributedCacheMiddleware(
            redis_url="redis://redis-prod:6379/1",
            ttl_seconds=300,
            max_size=5000,
        ))
        
        # 3. 分布式限流（priority=150，mandatory）
        p.add_middleware(DistributedRateLimitMiddleware(
            redis_url="redis://redis-prod:6379",
            max_requests=100,
            window_seconds=60.0,
            max_tool_calls=30,
            tool_call_window=60.0,
            fallback_allow=False,
        ))
        
        # 4. 安全护栏（priority=200，mandatory）
        p.add_middleware(SafetyGuardrailMiddleware(
            enable_pii_masking=True,
        ))
        
        # 5. 上下文管理（priority=300）
        p.add_middleware(ContextWindowMiddleware(
            max_tokens=8000,
            keep_rounds=5,
        ))
        
        return p

# 使用
async def main():
    pipeline = await create_production_pipeline()
    
    ctx = AgentContext(
        session_id="user-456",
        messages=[Message(role="user", content="帮我查询天气")]
    )
    
    response = await pipeline.run(ctx)
    print(response.content)

asyncio.run(main())
```

---

## 5. 监控与告警

### Prometheus 指标集成

```python
from prometheus_client import Gauge, Counter

# 定义指标
RATE_LIMIT_REMAINING = Gauge(
    'onion_rate_limit_remaining',
    'Remaining rate limit quota',
    ['session_id', 'limit_type']
)

CACHE_HIT_RATE = Gauge(
    'onion_cache_hit_rate',
    'Cache hit rate percentage'
)

# 在中间件中上报
async def report_metrics(rate_limiter, cache):
    usage = await rate_limiter.get_usage("user-123")
    
    RATE_LIMIT_REMAINING.labels(
        session_id="user-123",
        limit_type="request"
    ).set(usage["request_remaining"])
    
    RATE_LIMIT_REMAINING.labels(
        session_id="user-123",
        limit_type="tool_call"
    ).set(usage["tool_call_remaining"])
    
    CACHE_HIT_RATE.set(cache.hit_rate * 100)
```

### Grafana 仪表板示例

```json
{
  "dashboard": {
    "title": "Onion Core Distributed Metrics",
    "panels": [
      {
        "title": "Cache Hit Rate",
        "targets": [{"expr": "onion_cache_hit_rate"}]
      },
      {
        "title": "Rate Limit Remaining",
        "targets": [{"expr": "onion_rate_limit_remaining"}]
      },
      {
        "title": "Redis Connection Pool Usage",
        "targets": [{"expr": "redis_connected_clients"}]
      }
    ]
  }
}
```

---

## 6. 故障排查

### 常见问题

#### Q1: Redis 连接失败

```python
# 错误：redis.exceptions.ConnectionError: Error connecting to Redis
# 解决：检查 Redis 服务和网络
redis-cli ping  # 应返回 PONG

# 检查防火墙
telnet redis-host 6379
```

#### Q2: 限流未按预期工作

```python
# 问题：多实例间限流状态不一致
# 原因：每个实例连接到不同的 Redis 实例
# 解决：确保所有实例使用相同的 Redis URL

# 验证：查看所有实例的 Redis 连接
redis-cli CLIENT LIST | grep addr
```

#### Q3: 缓存命中率低

```python
# 诊断：检查缓存键生成策略
cache = DistributedCacheMiddleware(cache_key_strategy="full")
# 如果消息顺序不同会导致缓存未命中

# 解决：改用 user_only 策略或自定义缓存键
cache = DistributedCacheMiddleware(cache_key_strategy="user_only")
```

### 调试模式

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 查看 Redis 操作
redis-cli MONITOR
```

---

## 7. 性能基准

### 测试环境

- Redis: 6.2.7, 8GB RAM, SSD
- Onion Core: 3 实例，每实例 4 CPU
- 网络：内网 <1ms 延迟

### 基准结果

| 场景 | 吞吐量 (QPS) | P95 延迟 | 说明 |
|------|-------------|---------|------|
| 无限流无缓存 | 150 | 520ms | 纯 LLM 调用 |
| + 分布式限流 | 145 | 525ms | +5ms Redis 开销 |
| + 分布式缓存（miss） | 140 | 530ms | +10ms 序列化开销 |
| + 分布式缓存（hit） | 2000+ | 5ms | 90% 性能提升 |

### 优化建议

1. **Redis 连接池**：`pool_size = CPU cores × 2`
2. **缓存 TTL**：根据业务场景调整（FAQ: 1h, 对话: 5min）
3. **限流窗口**：避免过短窗口（<10s）导致 Redis 压力过大

---

## 8. 最佳实践

### ✅ 推荐做法

1. **使用独立的 Redis Database**
   ```python
   redis_url="redis://localhost:6379/1"  # 限流用 DB 1
   redis_url="redis://localhost:6379/2"  # 缓存用 DB 2
   ```

2. **设置合理的 fallback_allow**
   ```python
   # 生产环境：安全优先
   fallback_allow=False  # Redis 故障时拒绝请求
   
   # 内部工具：可用性优先
   fallback_allow=True   # Redis 故障时跳过限流
   ```

3. **定期清理过期缓存**
   ```python
   # Redis 自动处理（TTL），无需手动清理
   # 但建议监控内存使用
   redis-cli INFO memory
   ```

### ❌ 避免的做法

1. **不要在高频循环中创建中间件实例**
   ```python
   # ❌ 错误：每次请求都创建新连接
   for req in requests:
       middleware = DistributedRateLimitMiddleware(...)
   
   # ✅ 正确：复用中间件实例
   middleware = DistributedRateLimitMiddleware(...)
   for req in requests:
       await middleware.process_request(req)
   ```

2. **不要使用默认的 localhost 在生产环境**
   ```python
   # ❌ 错误
   redis_url="redis://localhost:6379"
   
   # ✅ 正确
   redis_url="redis://redis-cluster.prod.internal:6379"
   ```

---

## 下一步

- 📖 [架构设计文档](architecture.md)
- 🔧 [配置管理指南](how-to-guides/load-config-from-file.md)
- 📊 [监控指南](monitoring_guide.md)

---

**需要帮助？** 提交 Issue 或联系技术支持。
