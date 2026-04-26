"""Tests for distributed middleware with Redis backend (using mock)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from onion_core import (
    AgentContext,
    CacheHitException,
    EchoProvider,
    Message,
    Pipeline,
)
from onion_core.middlewares import (
    DistributedCacheMiddleware,
    DistributedRateLimitMiddleware,
)


class TestDistributedRateLimitMiddleware:
    """Test distributed rate limiting with mocked Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.script_load = AsyncMock(return_value="mock_script_sha")
        mock.evalsha = AsyncMock(return_value=[5, 0])  # remaining=5, retry_after=0
        mock.aclose = AsyncMock()
        return mock

    @pytest.fixture
    async def rate_limiter(self, mock_redis):
        """Create rate limiter with mocked Redis."""
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            limiter = DistributedRateLimitMiddleware(
                redis_url="redis://localhost:6379",
                max_requests=10,
                window_seconds=60.0,
            )
            
            # Manually set the redis client
            limiter._redis = mock_redis
            await limiter.startup()
            
            yield limiter
            
            await limiter.shutdown()

    async def test_startup_connects_to_redis(self, mock_redis):
        """Test that startup connects to Redis and loads Lua script."""
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            limiter = DistributedRateLimitMiddleware(
                redis_url="redis://localhost:6379",
                max_requests=10,
            )
            limiter._redis = mock_redis
            await limiter.startup()
            
            mock_redis.ping.assert_called_once()
            mock_redis.script_load.assert_called_once()
            
            await limiter.shutdown()

    async def test_process_request_allows_within_limit(self, rate_limiter, mock_redis):
        """Test that requests within limit are allowed."""
        ctx = AgentContext(
            session_id="test-user",
            messages=[Message(role="user", content="Hello")],
        )
        
        result = await rate_limiter.process_request(ctx)
        
        assert result is ctx
        assert "rate_limit_remaining" in ctx.metadata
        assert ctx.metadata["rate_limit_remaining"] == 5
        
        # Verify evalsha was called with correct parameters
        mock_redis.evalsha.assert_called_once()
        call_args = mock_redis.evalsha.call_args
        assert call_args[0][0] == "mock_script_sha"
        assert call_args[0][1] == 1  # number of keys

    async def test_process_request_blocks_when_exceeded(self, rate_limiter, mock_redis):
        """Test that requests are blocked when limit exceeded."""
        # Mock Redis to return rate limit exceeded
        mock_redis.evalsha = AsyncMock(return_value=[-1, 30.5])  # remaining=-1, retry_after=30.5
        
        ctx = AgentContext(
            session_id="test-user",
            messages=[Message(role="user", content="Hello")],
        )
        
        from onion_core.models import RateLimitExceeded
        
        with pytest.raises(RateLimitExceeded) as exc_info:
            await rate_limiter.process_request(ctx)
        
        assert "Retry after 30.5s" in str(exc_info.value)

    async def test_get_usage_returns_stats(self, rate_limiter, mock_redis):
        """Test get_usage returns layered stats (requests + tool calls)."""
        # Mock both request and tool call keys
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(side_effect=[7, 3])  # 7 requests, 3 tool calls
        
        usage = await rate_limiter.get_usage("test-user")
        
        assert usage["session_id"] == "test-user"
        assert usage["requests_in_window"] == 7
        assert usage["max_requests"] == 10
        assert usage["request_remaining"] == 3
        assert usage["tool_calls_in_window"] == 3
        assert usage["max_tool_calls"] == 10  # Default equals max_requests
        assert usage["tool_call_remaining"] == 7
        assert usage["distributed"] is True

    async def test_reset_session_deletes_key(self, rate_limiter, mock_redis):
        """Test reset_session deletes both request and tool call keys."""
        mock_redis.delete = AsyncMock()
        
        await rate_limiter.reset_session("test-user")
        
        # Should delete both :req and :tool keys
        mock_redis.delete.assert_called_once_with(
            "onion:ratelimit:test-user:req",
            "onion:ratelimit:test-user:tool"
        )

    async def test_fallback_allow_on_redis_error(self):
        """Test that fallback_allow permits requests when Redis fails."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis down"))
        
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            limiter = DistributedRateLimitMiddleware(
                redis_url="redis://localhost:6379",
                max_requests=10,
                fallback_allow=True,  # Allow on failure
            )
            limiter._redis = mock_redis
            
            # Should not raise during startup
            await limiter.startup()
            
            ctx = AgentContext(
                session_id="test-user",
                messages=[Message(role="user", content="Hello")],
            )
            
            # Should allow request despite Redis error
            result = await limiter.process_request(ctx)
            assert result is ctx
            
            await limiter.shutdown()

    async def test_reset_all_clears_all_keys(self, rate_limiter, mock_redis):
        """Test reset_all clears all rate limit keys."""
        mock_redis.scan = AsyncMock(side_effect=[
            (0, ["onion:ratelimit:user1", "onion:ratelimit:user2"]),
        ])
        mock_redis.delete = AsyncMock()
        
        await rate_limiter.reset_all()
        
        mock_redis.delete.assert_called_once_with(
            "onion:ratelimit:user1", "onion:ratelimit:user2"
        )

    async def test_get_usage_without_redis_raises_error(self):
        """Test get_usage raises RuntimeError when Redis not initialized."""
        limiter = DistributedRateLimitMiddleware.__new__(DistributedRateLimitMiddleware)
        limiter._redis = None
        
        with pytest.raises(RuntimeError, match="Redis not initialized"):
            await limiter.get_usage("test-user")

    async def test_reset_session_without_redis_raises_error(self):
        """Test reset_session raises RuntimeError when Redis not initialized."""
        limiter = DistributedRateLimitMiddleware.__new__(DistributedRateLimitMiddleware)
        limiter._redis = None
        
        with pytest.raises(RuntimeError, match="Redis not initialized"):
            await limiter.reset_session("test-user")

    async def test_reset_all_without_redis_raises_error(self):
        """Test reset_all raises RuntimeError when Redis not initialized."""
        limiter = DistributedRateLimitMiddleware.__new__(DistributedRateLimitMiddleware)
        limiter._redis = None
        
        with pytest.raises(RuntimeError, match="Redis not initialized"):
            await limiter.reset_all()

    async def test_process_stream_chunk_passthrough(self, rate_limiter):
        """Test process_stream_chunk passes through unchanged."""
        from onion_core.models import StreamChunk
        
        ctx = AgentContext(messages=[Message(role="user", content="Hi")])
        chunk = StreamChunk(delta="test", index=0)
        
        result = await rate_limiter.process_stream_chunk(ctx, chunk)
        assert result is chunk

    async def test_on_tool_call_passthrough(self, rate_limiter):
        """Test on_tool_call passes through unchanged."""
        from onion_core.models import ToolCall
        
        ctx = AgentContext(messages=[Message(role="user", content="Hi")])
        tool_call = ToolCall(id="call_1", name="test_tool", arguments={})
        
        result = await rate_limiter.on_tool_call(ctx, tool_call)
        assert result is tool_call

    async def test_on_tool_result_passthrough(self, rate_limiter):
        """Test on_tool_result passes through unchanged."""
        from onion_core.models import ToolResult
        
        ctx = AgentContext(messages=[Message(role="user", content="Hi")])
        tool_result = ToolResult(tool_call_id="call_1", name="test_tool", result="ok")
        
        result = await rate_limiter.on_tool_result(ctx, tool_result)
        assert result is tool_result

    async def test_on_error_logs_error(self, rate_limiter, caplog):
        """Test on_error logs the error."""
        import logging
        caplog.set_level(logging.ERROR)
        
        ctx = AgentContext(messages=[Message(role="user", content="Hi")])
        error = ValueError("Test error")
        
        await rate_limiter.on_error(ctx, error)
        
        assert "DistributedRateLimitMiddleware error" in caplog.text

    async def test_get_usage_handles_redis_error(self, rate_limiter, mock_redis):
        """Test get_usage returns error dict when Redis fails."""
        mock_redis.zremrangebyscore = AsyncMock(side_effect=ConnectionError("Fail"))
        
        usage = await rate_limiter.get_usage("test-user")
        
        assert "error" in usage
        assert usage["distributed"] is True
        assert "Fail" in usage["error"]

    async def test_fallback_deny_on_redis_error_during_request(self):
        """Test that fallback_allow=False rejects requests when Redis fails."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.script_load = AsyncMock(return_value="mock_sha")
        mock_redis.evalsha = AsyncMock(side_effect=ConnectionError("Redis down"))
        
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            limiter = DistributedRateLimitMiddleware(
                redis_url="redis://localhost:6379",
                max_requests=10,
                fallback_allow=False,  # Deny on failure
            )
            limiter._redis = mock_redis
            limiter._lua_script_sha = "mock_sha"
            await limiter.startup()
            
            ctx = AgentContext(
                session_id="test-user",
                messages=[Message(role="user", content="Hello")],
            )
            
            from onion_core.models import RateLimitExceeded
            
            with pytest.raises(RateLimitExceeded, match="Rate limiter unavailable"):
                await limiter.process_request(ctx)
            
            await limiter.shutdown()


class TestDistributedCacheMiddleware:
    """Test distributed caching with mocked Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.aclose = AsyncMock()
        return mock

    @pytest.fixture
    async def cache_middleware(self, mock_redis):
        """Create cache middleware with mocked Redis."""
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            cache = DistributedCacheMiddleware(
                redis_url="redis://localhost:6379",
                ttl_seconds=300,
            )
            
            # Manually set the redis client
            cache._redis = mock_redis
            await cache.startup()
            
            yield cache
            
            await cache.shutdown()

    async def test_startup_connects_to_redis(self, mock_redis):
        """Test that startup connects to Redis."""
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            cache = DistributedCacheMiddleware(
                redis_url="redis://localhost:6379",
                ttl_seconds=300,
            )
            cache._redis = mock_redis
            await cache.startup()
            
            mock_redis.ping.assert_called_once()
            
            await cache.shutdown()

    async def test_cache_miss_on_first_request(self, cache_middleware, mock_redis):
        """Test that first request is a cache miss."""
        mock_redis.get = AsyncMock(return_value=None)  # Cache miss
        
        ctx = AgentContext(
            messages=[Message(role="user", content="Hello")],
        )
        
        result = await cache_middleware.process_request(ctx)
        
        assert result is ctx
        assert cache_middleware.misses == 1
        assert cache_middleware.hits == 0

    async def test_cache_hit_on_second_request(self, cache_middleware, mock_redis):
        """Test that second identical request is a cache hit and raises CacheHitException."""
        # First request - cache miss
        mock_redis.get = AsyncMock(return_value=None)
        ctx1 = AgentContext(
            messages=[Message(role="user", content="Hello")],
        )
        await cache_middleware.process_request(ctx1)
        
        # Second request - cache hit
        cached_data = '{"content": "Cached response", "tool_calls": [], "finish_reason": "stop", "usage": null, "model": "echo"}'
        mock_redis.get = AsyncMock(return_value=cached_data)
        
        ctx2 = AgentContext(
            messages=[Message(role="user", content="Hello")],
        )
        with pytest.raises(CacheHitException) as exc_info:
            await cache_middleware.process_request(ctx2)
        
        assert exc_info.value.cached_response.content == "Cached response"
        assert cache_middleware.hits == 1
        assert cache_middleware.misses == 1

    async def test_process_response_passthrough_on_miss(self, cache_middleware):
        """Test that process_response passes through response on cache miss."""
        from onion_core.models import FinishReason, LLMResponse
        
        ctx = AgentContext(
            messages=[Message(role="user", content="Hello")],
        )
        
        response = LLMResponse(
            content="New response",
            finish_reason=FinishReason.LENGTH,
        )
        
        result = await cache_middleware.process_response(ctx, response)
        
        assert result is response

    async def test_process_response_caches_new_response(self, cache_middleware, mock_redis):
        """Test that process_response caches new responses."""
        from onion_core.models import FinishReason, LLMResponse
        
        mock_redis.setex = AsyncMock()
        
        ctx = AgentContext(
            messages=[Message(role="user", content="Hello")],
        )
        
        response = LLMResponse(
            content="New response",
            finish_reason=FinishReason.STOP,
            model="echo",
        )
        
        result = await cache_middleware.process_response(ctx, response)
        
        # Verify setex was called to cache the response
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 300  # TTL
        
        assert result is response  # Returns original response

    async def test_streaming_not_cached(self, cache_middleware):
        """Test that streaming chunks pass through without caching."""
        from onion_core.models import StreamChunk
        
        ctx = AgentContext(messages=[Message(role="user", content="Hello")])
        chunk = StreamChunk(delta="test", index=0)
        
        result = await cache_middleware.process_stream_chunk(ctx, chunk)
        
        assert result is chunk

    async def test_hit_rate_calculation(self, cache_middleware):
        """Test hit rate calculation."""
        # Simulate hits and misses
        cache_middleware._hits = 8
        cache_middleware._misses = 2
        
        assert cache_middleware.hit_rate == 0.8
        assert cache_middleware.hits == 8
        assert cache_middleware.misses == 2

    async def test_clear_cache_deletes_keys(self, cache_middleware, mock_redis):
        """Test clear_cache deletes all cache keys."""
        mock_redis.scan = AsyncMock(side_effect=[
            (0, ["onion:cache:key1", "onion:cache:key2"]),  # First scan returns keys
        ])
        mock_redis.delete = AsyncMock()
        
        await cache_middleware.clear_cache()
        
        mock_redis.delete.assert_called_once_with("onion:cache:key1", "onion:cache:key2")

    async def test_get_cache_size_counts_keys(self, cache_middleware, mock_redis):
        """Test get_cache_size returns correct count."""
        mock_redis.scan = AsyncMock(side_effect=[
            (0, ["key1", "key2", "key3"]),
        ])
        
        size = await cache_middleware.get_cache_size()
        
        assert size == 3

    async def test_serialization_deserialization_roundtrip(self, cache_middleware):
        """Test that serialization and deserialization preserve data."""
        from onion_core.models import FinishReason, LLMResponse, ToolCall, UsageStats
        
        original = LLMResponse(
            content="Test content",
            tool_calls=[
                ToolCall(id="call_1", name="get_weather", arguments={"city": "Beijing"})
            ],
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            model="gpt-4",
        )
        
        # Serialize
        serialized = cache_middleware._serialize_response(original)
        
        # Deserialize
        restored = cache_middleware._deserialize_response(serialized)
        
        assert restored.content == original.content
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].name == "get_weather"
        assert restored.finish_reason == FinishReason.STOP
        assert restored.usage.total_tokens == 30
        assert restored.model == "gpt-4"


class TestIntegrationWithPipeline:
    """Test integration of distributed middleware with Pipeline."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.script_load = AsyncMock(return_value="mock_sha")
        mock.evalsha = AsyncMock(return_value=[5, 0])
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock()
        mock.aclose = AsyncMock()
        return mock

    async def test_pipeline_with_distributed_rate_limit(self, mock_redis):
        """Test Pipeline with distributed rate limiter."""
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            limiter = DistributedRateLimitMiddleware(
                redis_url="redis://localhost:6379",
                max_requests=10,
                fallback_allow=True,  # Allow on Redis error for testing
            )
            
            async with Pipeline(provider=EchoProvider()) as p:
                p.add_middleware(limiter)
                
                ctx = AgentContext(
                    session_id="test-user",
                    messages=[Message(role="user", content="Hello")],
                )
                
                response = await p.run(ctx)
                
                assert response.content is not None

    async def test_pipeline_with_distributed_cache(self, mock_redis):
        """Test Pipeline with distributed cache."""
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            cache = DistributedCacheMiddleware(
                redis_url="redis://localhost:6379",
                ttl_seconds=300,
            )
            cache._redis = mock_redis
            
            async with Pipeline(provider=EchoProvider(reply="Test")) as p:
                p.add_middleware(cache)
                
                ctx = AgentContext(
                    messages=[Message(role="user", content="Hello")],
                )
                
                response = await p.run(ctx)
                
                assert response.content == "Test"
                mock_redis.setex.assert_called()

    async def test_distributed_rate_limit_redis_unavailable_fallback_allow(self):
        """Test DistributedRateLimitMiddleware with Redis unavailable and fallback_allow=True."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
        
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            limiter = DistributedRateLimitMiddleware(
                redis_url="redis://unreachable:6379",
                max_requests=10,
                fallback_allow=True,  # Allow on failure
            )
            
            # Startup should not raise due to fallback_allow
            await limiter.startup()
            
            ctx = AgentContext(
                session_id="test-user",
                messages=[Message(role="user", content="Hello")],
            )
            
            # Should allow request despite Redis being down
            result = await limiter.process_request(ctx)
            assert result is ctx
            assert ctx.metadata.get("rate_limit_remaining") == -1  # Unknown
            
            await limiter.shutdown()

    async def test_distributed_rate_limit_redis_unavailable_fallback_deny(self):
        """Test DistributedRateLimitMiddleware with Redis unavailable and fallback_allow=False."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
        
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            limiter = DistributedRateLimitMiddleware(
                redis_url="redis://unreachable:6379",
                max_requests=10,
                fallback_allow=False,  # Deny on failure
            )
            
            # Startup should raise due to fallback_allow=False
            with pytest.raises(ConnectionError):
                await limiter.startup()

    async def test_distributed_cache_redis_unavailable_raises(self):
        """Test DistributedCacheMiddleware raises error when Redis unavailable."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
        
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            cache = DistributedCacheMiddleware(
                redis_url="redis://unreachable:6379",
                ttl_seconds=300,
            )
            
            # Startup should raise
            with pytest.raises(ConnectionError):
                await cache.startup()

    async def test_distributed_circuit_breaker_redis_unavailable_fallback_allow(self):
        """Test DistributedCircuitBreakerMiddleware with Redis unavailable and fallback_allow=True."""
        from onion_core.middlewares import DistributedCircuitBreakerMiddleware
        
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
        
        with patch("redis.asyncio.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis
            
            breaker = DistributedCircuitBreakerMiddleware(
                redis_url="redis://unreachable:6379",
                failure_threshold=5,
                recovery_timeout=30.0,
                fallback_allow=True,  # Allow on failure
            )
            
            # Startup should not raise due to fallback_allow
            await breaker.startup()
            
            ctx = AgentContext(
                session_id="test-user",
                messages=[Message(role="user", content="Hello")],
                metadata={"provider_name": "test-provider"},
            )
            
            # Should allow request despite Redis being down
            result = await breaker.process_request(ctx)
            assert result is ctx
            
            await breaker.shutdown()
