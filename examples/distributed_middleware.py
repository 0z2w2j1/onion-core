"""
Onion Core - Distributed Middleware Examples

展示如何使用基于 Redis 的分布式中间件：
- DistributedRateLimitMiddleware（分布式限流）
- DistributedCacheMiddleware（分布式缓存）

前置条件：
1. 安装 Redis: https://redis.io/download
2. 启动 Redis 服务
3. 安装依赖: pip install "onion-core[redis]"

运行示例：
    python examples/distributed_middleware.py
"""

import asyncio

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import (
    DistributedCacheMiddleware,
    DistributedRateLimitMiddleware,
)


async def example_distributed_rate_limit():
    """示例 1: 分布式限流"""
    print("=" * 60)
    print("示例 1: 分布式限流（Redis 后端）")
    print("=" * 60)

    # 创建分布式限流中间件
    rate_limiter = DistributedRateLimitMiddleware(
        redis_url="redis://localhost:6379",
        max_requests=5,  # 每 60 秒最多 5 次请求
        window_seconds=60.0,
        key_prefix="onion:ratelimit",
        fallback_allow=False,  # Redis 不可用时拒绝请求
    )

    async with Pipeline(provider=EchoProvider()) as p:
        p.add_middleware(rate_limiter)

        # 模拟多个请求
        for i in range(7):
            ctx = AgentContext(
                session_id="user-123",  # 同一用户
                messages=[Message(role="user", content=f"Request {i + 1}")],
            )

            try:
                response = await p.run(ctx)
                remaining = ctx.metadata.get("rate_limit_remaining", "unknown")
                print(f"✓ Request {i + 1}: {response.content[:30]}... (remaining: {remaining})")
            except Exception as e:
                print(f"✗ Request {i + 1} blocked: {type(e).__name__}: {e}")

    # 查询限流状态
    usage = await rate_limiter.get_usage("user-123")
    print(f"\n限流状态: {usage}")

    # 重置限流
    await rate_limiter.reset_session("user-123")
    print("已重置用户 user-123 的限流计数\n")


async def example_distributed_cache():
    """示例 2: 分布式缓存"""
    print("=" * 60)
    print("示例 2: 分布式缓存（Redis 后端）")
    print("=" * 60)

    # 创建分布式缓存中间件
    cache = DistributedCacheMiddleware(
        redis_url="redis://localhost:6379",
        ttl_seconds=300,  # 缓存 5 分钟
        max_size=1000,
        key_prefix="onion:cache",
        cache_key_strategy="full",  # 使用完整消息生成缓存键
    )

    async with Pipeline(provider=EchoProvider(reply="Cached response")) as p:
        p.add_middleware(cache)

        # 第一次请求（缓存未命中）
        ctx1 = AgentContext(
            messages=[Message(role="user", content="Hello")]
        )
        print("\n第一次请求（缓存未命中）:")
        response1 = await p.run(ctx1)
        print(f"  响应: {response1.content}")
        print(f"  缓存命中率: {cache.hit_rate * 100:.1f}%")

        # 第二次相同请求（缓存命中）
        ctx2 = AgentContext(
            messages=[Message(role="user", content="Hello")]
        )
        print("\n第二次相同请求（缓存命中）:")
        response2 = await p.run(ctx2)
        print(f"  响应: {response2.content}")
        print(f"  缓存命中率: {cache.hit_rate * 100:.1f}%")

        # 不同请求（缓存未命中）
        ctx3 = AgentContext(
            messages=[Message(role="user", content="World")]
        )
        print("\n第三次不同请求（缓存未命中）:")
        response3 = await p.run(ctx3)
        print(f"  响应: {response3.content}")
        print(f"  缓存命中率: {cache.hit_rate * 100:.1f}%")

    # 查询缓存大小
    cache_size = await cache.get_cache_size()
    print(f"\n缓存条目数: {cache_size}")

    # 清空缓存
    await cache.clear_cache()
    print("已清空缓存\n")


async def example_combined():
    """示例 3: 组合使用分布式限流和缓存"""
    print("=" * 60)
    print("示例 3: 组合使用分布式限流 + 缓存")
    print("=" * 60)

    # 创建中间件
    rate_limiter = DistributedRateLimitMiddleware(
        redis_url="redis://localhost:6379",
        max_requests=10,
        window_seconds=60.0,
    )

    cache = DistributedCacheMiddleware(
        redis_url="redis://localhost:6379",
        ttl_seconds=300,
    )

    async with Pipeline(provider=EchoProvider(reply="Combined response")) as p:
        # 注意顺序：先限流，再缓存
        p.add_middleware(rate_limiter)
        p.add_middleware(cache)

        # 模拟并发请求
        tasks = []
        for _ in range(5):
            ctx = AgentContext(
                session_id="user-456",
                messages=[Message(role="user", content="Test")],
            )
            tasks.append(p.run(ctx))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if not isinstance(r, Exception))
        error_count = sum(1 for r in results if isinstance(r, Exception))

        print(f"\n成功请求: {success_count}")
        print(f"失败请求: {error_count}")
        print(f"缓存命中率: {cache.hit_rate * 100:.1f}%")

    print()


async def main():
    """运行所有示例"""
    print("\n🧅 Onion Core - 分布式中间件示例\n")

    try:
        # 检查 Redis 连接
        import redis.asyncio as redis

        test_redis = redis.Redis(host="localhost", port=6379)
        await test_redis.ping()
        await test_redis.aclose()
        print("✓ Redis 连接成功\n")
    except Exception as e:
        print(f"✗ Redis 连接失败: {e}")
        print("请确保 Redis 服务正在运行: redis-server\n")
        return

    # 运行示例
    await example_distributed_rate_limit()
    await example_distributed_cache()
    await example_combined()

    print("✅ 所有示例运行完成！")


if __name__ == "__main__":
    asyncio.run(main())
