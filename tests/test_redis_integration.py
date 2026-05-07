"""Optional integration tests against a real Redis server.

Set ONION_REDIS_URL, for example:

    ONION_REDIS_URL=redis://localhost:6379/15 python -m pytest tests/test_redis_integration.py -q
"""

from __future__ import annotations

import os
import uuid

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline, RateLimitExceeded
from onion_core.middlewares import (
    DistributedCacheMiddleware,
    DistributedCircuitBreakerMiddleware,
    DistributedRateLimitMiddleware,
)
from onion_core.models import CircuitBreakerError, FinishReason, LLMResponse

redis = pytest.importorskip("redis.asyncio")

REDIS_URL = os.getenv("ONION_REDIS_URL")

pytestmark = pytest.mark.skipif(
    not REDIS_URL,
    reason="set ONION_REDIS_URL to run real Redis integration tests",
)


@pytest.fixture
def redis_prefix() -> str:
    return f"onion:test:{uuid.uuid4().hex}"


@pytest.fixture
async def redis_client(redis_prefix: str):
    assert REDIS_URL is not None
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis unavailable at ONION_REDIS_URL: {exc}")
    try:
        yield client
    finally:
        cursor = 0
        pattern = f"{redis_prefix}:*"
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
        await client.aclose()


class CountingProvider(EchoProvider):
    def __init__(self) -> None:
        super().__init__(reply=None)
        self.calls = 0

    async def complete(self, context: AgentContext) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content=f"call-{self.calls}",
            finish_reason=FinishReason.STOP,
            model="redis-integration",
        )


@pytest.mark.asyncio
async def test_distributed_cache_uses_real_redis(redis_client, redis_prefix: str):
    assert REDIS_URL is not None
    provider = CountingProvider()
    cache = DistributedCacheMiddleware(
        redis_url=REDIS_URL,
        key_prefix=f"{redis_prefix}:cache",
        namespace="redis-integration",
        ttl_seconds=30,
    )
    pipeline = Pipeline(provider=provider).add_middleware(cache)

    async with pipeline:
        ctx1 = AgentContext(messages=[Message(role="user", content="cache me")])
        ctx2 = AgentContext(messages=[Message(role="user", content="cache me")])
        first = await pipeline.run(ctx1)
        second = await pipeline.run(ctx2)

    assert first.content == "call-1"
    assert second.content == "call-1"
    assert provider.calls == 1
    assert cache.hits == 1
    assert cache.misses == 1


@pytest.mark.asyncio
async def test_distributed_rate_limit_blocks_with_real_redis(redis_client, redis_prefix: str):
    assert REDIS_URL is not None
    limiter = DistributedRateLimitMiddleware(
        redis_url=REDIS_URL,
        key_prefix=f"{redis_prefix}:ratelimit",
        max_requests=1,
        window_seconds=30,
    )
    await limiter.startup()
    try:
        session_id = f"sess-{uuid.uuid4().hex}"
        ctx1 = AgentContext(
            session_id=session_id,
            messages=[Message(role="user", content="first")],
        )
        ctx2 = AgentContext(
            session_id=session_id,
            messages=[Message(role="user", content="second")],
        )

        await limiter.process_request(ctx1)
        with pytest.raises(RateLimitExceeded):
            await limiter.process_request(ctx2)
    finally:
        await limiter.shutdown()


@pytest.mark.asyncio
async def test_distributed_circuit_breaker_uses_real_redis(redis_client, redis_prefix: str):
    assert REDIS_URL is not None
    provider_name = "redis-provider"
    breaker = DistributedCircuitBreakerMiddleware(
        redis_url=REDIS_URL,
        key_prefix=f"{redis_prefix}:cb",
        failure_threshold=1,
        recovery_timeout=30,
        success_threshold=1,
    )
    breaker.add_provider(provider_name)

    await breaker.startup()
    try:
        ctx = AgentContext(
            messages=[Message(role="user", content="hello")],
            metadata={"provider_name": provider_name},
        )

        await breaker.process_request(ctx)
        await breaker.on_error(ctx, RuntimeError("provider failed"))

        status = await breaker.get_status(provider_name)
        assert status["state"] == "OPEN"
        assert status["failure_count"] == 1

        blocked_ctx = AgentContext(
            messages=[Message(role="user", content="blocked")],
            metadata={"provider_name": provider_name},
        )
        with pytest.raises(CircuitBreakerError):
            await breaker.process_request(blocked_ctx)
    finally:
        await breaker.reset(provider_name)
        await breaker.shutdown()
