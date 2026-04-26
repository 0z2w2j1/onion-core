# 如何配置 Redis 分布式限流

本指南展示如何配置基于 Redis 的分布式限流，支持多实例共享限流状态。

## 前提条件

- 已安装 Redis 服务器
- 已安装 `redis` Python 包：`pip install redis>=5.0`

## 基本配置

```python
from onion_core import Pipeline, EchoProvider
from onion_core.middlewares import DistributedRateLimitMiddleware

async def main():
    # 创建分布式限流中间件
    rate_limit_mw = DistributedRateLimitMiddleware(
        redis_url="redis://localhost:6379",
        max_requests=60,          # 每窗口最大请求数
        window_seconds=60.0,      # 时间窗口（秒）
        key_prefix="onion:ratelimit",
        pool_size=10,             # Redis 连接池大小
    )
    
    async with Pipeline(provider=EchoProvider()) as p:
        p.add_middleware(rate_limit_mw)
        
        # 执行请求...
```

## 分层限流（普通请求 vs 工具调用）

为防止工具调用风暴耗尽配额，可以配置独立的工具调用限流：

```python
rate_limit_mw = DistributedRateLimitMiddleware(
    redis_url="redis://localhost:6379",
    max_requests=60,              # 普通请求：60次/分钟
    window_seconds=60.0,
    max_tool_calls=20,            # 工具调用：20次/分钟（独立限额）
    tool_call_window=60.0,
)
```

中间件会自动检测消息中是否包含 `role="tool"` 的结果，并应用对应的限流策略。

## 降级策略

当 Redis 不可用时，可以选择允许或拒绝请求：

```python
rate_limit_mw = DistributedRateLimitMiddleware(
    redis_url="redis://localhost:6379",
    fallback_allow=True,  # Redis 故障时允许请求通过（默认 False）
)
```

## 监控限流状态

```python
# 获取当前会话的限流使用情况
usage = rate_limit_mw.get_usage(session_id="user_123")
print(f"剩余请求数: {usage['request_remaining']}")
print(f"剩余工具调用数: {usage['tool_call_remaining']}")
```

## 重置限流计数

```python
# 重置特定会话
await rate_limit_mw.reset_session("user_123")

# 重置所有会话
await rate_limit_mw.reset_all()
```

## 常见问题

### Q: Redis 连接超时怎么办？

A: 检查 Redis 服务器是否运行，并确认防火墙规则允许连接。可以调整超时参数：

```python
import redis.asyncio as redis

pool = redis.ConnectionPool.from_url(
    "redis://localhost:6379",
    socket_connect_timeout=5.0,
    socket_timeout=5.0,
)
```

### Q: 如何验证限流是否生效？

A: 快速发送多个请求，观察是否抛出 `RateLimitExceeded` 异常：

```python
from onion_core.models import RateLimitExceeded

for i in range(100):
    try:
        await p.run(ctx)
    except RateLimitExceeded as e:
        print(f"在第 {i+1} 次请求时被限流: {e}")
        break
```

## 下一步

- 查看 **[分布式中间件架构解释](../explanation/distributed-architecture.md)** 了解实现原理
- 参考 **[API 参考：DistributedRateLimitMiddleware](../api/middlewares/ratelimit.md)** 查看所有配置选项
