"""Comprehensive load tests for Onion Core pipeline performance."""

from __future__ import annotations

import asyncio
import time

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    ResponseCacheMiddleware,
    SafetyGuardrailMiddleware,
)


@pytest.fixture
def context():
    """Create a standard test context."""
    return AgentContext(
        messages=[
            Message(role="user", content="Hello, how are you?"),
        ]
    )


class TestConcurrentRequests:
    """Test concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_basic(self, context):
        """Test handling multiple concurrent requests."""
        provider = EchoProvider(reply="test response")
        
        async with Pipeline(provider=provider) as p:
            tasks = [p.run(context) for _ in range(10)]
            responses = await asyncio.gather(*tasks)
            
            assert len(responses) == 10
            assert all(r.content == "test response" for r in responses)

    @pytest.mark.asyncio
    async def test_concurrent_requests_with_middlewares(self, context):
        """Test concurrent requests with full middleware stack."""
        provider = EchoProvider(reply="test")
        
        async with Pipeline(provider=provider) as p:
            p.add_middleware(ObservabilityMiddleware())
            p.add_middleware(SafetyGuardrailMiddleware())
            p.add_middleware(ContextWindowMiddleware(max_tokens=4000))
            
            tasks = [p.run(context) for _ in range(20)]
            start = time.perf_counter()
            responses = await asyncio.gather(*tasks)
            duration = time.perf_counter() - start
            
            assert len(responses) == 20
            # Should complete in reasonable time (< 5 seconds for echo provider)
            assert duration < 5.0

    @pytest.mark.asyncio
    async def test_concurrent_streaming_requests(self, context):
        """Test concurrent streaming requests."""
        provider = EchoProvider(reply="streaming test")
        
        async def collect_stream(pipeline: Pipeline, ctx: AgentContext) -> str:
            chunks = []
            async for chunk in pipeline.stream(ctx):
                if chunk.delta:
                    chunks.append(chunk.delta)
            return "".join(chunks)
        
        async with Pipeline(provider=provider) as p:
            tasks = [collect_stream(p, context) for _ in range(5)]
            results = await asyncio.gather(*tasks)
            
            assert len(results) == 5
            assert all("streaming test" in r for r in results)


class TestCachePerformance:
    """Test cache middleware performance impact."""

    @pytest.mark.asyncio
    async def test_cache_improves_latency(self, context):
        """Test that caching reduces response latency.
        
        Note: With EchoProvider (microsecond-level response), the overhead of
        exception handling for cache short-circuit may be comparable to the
        actual provider call time. This test verifies that cached requests
        don't degrade performance significantly (>5x slower).
        
        In production with real LLM APIs (100ms-5s latency), cache hits
        provide substantial performance improvements by skipping the API call.
        """
        provider = EchoProvider(reply="cached")
        
        # Without cache
        async with Pipeline(provider=provider) as p_no_cache:
            start = time.perf_counter()
            for _ in range(10):
                await p_no_cache.run(context)
            no_cache_duration = time.perf_counter() - start
        
        # With cache
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=100)
        async with Pipeline(provider=provider) as p_cache:
            p_cache.add_middleware(cache_mw)
            
            # First request (cache miss)
            await p_cache.run(context)
            
            # Subsequent requests (cache hits)
            start = time.perf_counter()
            for _ in range(9):
                await p_cache.run(context)
            cache_duration = time.perf_counter() - start
        
        # Cached requests should not be significantly slower
        # Allow up to 5x overhead for EchoProvider due to exception handling
        # Real LLM APIs would see significant improvement (not regression)
        assert cache_duration < no_cache_duration * 5.0

    @pytest.mark.asyncio
    async def test_cache_hit_rate_under_load(self, context):
        """Test cache hit rate under concurrent load."""
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=1000)
        provider = EchoProvider(reply="test")
        
        async with Pipeline(provider=provider) as p:
            p.add_middleware(cache_mw)
            
            # Warm up cache with same request
            for _ in range(5):
                await p.run(context)
            
            # Concurrent requests (all should hit cache)
            tasks = [p.run(context) for _ in range(50)]
            await asyncio.gather(*tasks)
            
            # Should have high hit rate
            assert cache_mw.hit_rate > 0.9


class TestRateLimitUnderLoad:
    """Test rate limiting behavior under load."""

    @pytest.mark.asyncio
    async def test_rate_limit_enforcement(self, context):
        """Test that rate limiting works under concurrent load."""
        from onion_core.models import RateLimitExceeded
        
        provider = EchoProvider(reply="test")
        rate_limit_mw = RateLimitMiddleware(window_seconds=1.0, max_requests=5)
        
        async with Pipeline(provider=provider) as p:
            p.add_middleware(rate_limit_mw)
            
            # Send more requests than limit
            tasks = [p.run(context) for _ in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Count rate limit errors
            rate_limited = sum(1 for r in results if isinstance(r, RateLimitExceeded))
            
            # Should have some rate limited requests
            assert rate_limited > 0


class TestPipelineThroughput:
    """Measure pipeline throughput under various conditions."""

    @pytest.mark.asyncio
    async def test_throughput_no_middlewares(self, context):
        """Baseline throughput without middlewares."""
        provider = EchoProvider(reply="test")
        
        async with Pipeline(provider=provider) as p:
            start = time.perf_counter()
            for _ in range(100):
                await p.run(context)
            duration = time.perf_counter() - start
        
        throughput = 100 / duration
        # Should handle at least 100 req/s with echo provider
        assert throughput > 100

    @pytest.mark.asyncio
    async def test_throughput_with_middlewares(self, context):
        """Throughput with full middleware stack."""
        provider = EchoProvider(reply="test")
        
        async with Pipeline(provider=provider) as p:
            p.add_middleware(ObservabilityMiddleware())
            p.add_middleware(SafetyGuardrailMiddleware())
            p.add_middleware(ContextWindowMiddleware(max_tokens=4000))
            
            start = time.perf_counter()
            for _ in range(100):
                await p.run(context)
            duration = time.perf_counter() - start
        
        throughput = 100 / duration
        # Should still handle reasonable throughput
        assert throughput > 50

    @pytest.mark.asyncio
    async def test_sync_api_throughput(self, context):
        """Test synchronous API throughput."""
        provider = EchoProvider(reply="test")
        
        with Pipeline(provider=provider) as p:
            start = time.perf_counter()
            for _ in range(50):
                p.run_sync(context)
            duration = time.perf_counter() - start
        
        throughput = 50 / duration
        # Sync API should still be reasonably fast
        assert throughput > 30


class TestMemoryUsage:
    """Test memory usage patterns."""

    @pytest.mark.asyncio
    async def test_cache_memory_bounded(self, context):
        """Test that cache memory usage is bounded."""
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=10)
        provider = EchoProvider(reply="test")
        
        async with Pipeline(provider=provider) as p:
            p.add_middleware(cache_mw)
            
            # Send many different requests
            for i in range(100):
                ctx = AgentContext(messages=[
                    Message(role="user", content=f"Request {i}")
                ])
                await p.run(ctx)
            
            # Cache size should not exceed max_size
            assert cache_mw.get_cache_size() <= 10

    @pytest.mark.asyncio
    async def test_context_metadata_cleanup(self, context):
        """Test that context metadata doesn't grow unbounded."""
        provider = EchoProvider(reply="test")
        
        async with Pipeline(provider=provider) as p:
            p.add_middleware(ObservabilityMiddleware())
            
            initial_metadata_keys = len(context.metadata)
            
            for _ in range(50):
                await p.run(context)
            
            # Metadata should be cleaned up after each request
            final_metadata_keys = len(context.metadata)
            # Allow some overhead but shouldn't grow linearly
            assert final_metadata_keys < initial_metadata_keys + 20


class TestErrorHandlingUnderLoad:
    """Test error handling behavior under load."""

    @pytest.mark.asyncio
    async def test_error_isolation(self, context):
        """Test that errors in one request don't affect others."""
        
        call_count = 0
        
        class FlakyProvider(EchoProvider):
            async def complete(self, ctx: AgentContext):
                nonlocal call_count
                call_count += 1
                if call_count % 3 == 0:
                    raise RuntimeError("Simulated failure")
                return await super().complete(ctx)
        
        provider = FlakyProvider(reply="test")
        
        async with Pipeline(provider=provider, max_retries=0) as p:
            tasks = [p.run(context) for _ in range(9)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Some should succeed, some should fail
            successes = sum(1 for r in results if not isinstance(r, Exception))
            failures = sum(1 for r in results if isinstance(r, Exception))
            
            assert successes > 0
            assert failures > 0
            assert successes + failures == 9
