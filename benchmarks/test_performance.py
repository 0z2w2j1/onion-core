"""Performance benchmarks for response caching and sync API."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import ResponseCacheMiddleware


@pytest.fixture
def context():
    return AgentContext(
        messages=[Message(role="user", content="Benchmark test message")]
    )


class TestResponseCacheBenchmarks:
    """Benchmarks for ResponseCacheMiddleware performance."""

    def test_cache_miss_latency(self, benchmark, context):
        """Benchmark cache miss latency (first request)."""
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=1000)
        provider = EchoProvider(reply="test")
        
        async def run():
            async with Pipeline(provider=provider) as p:
                p.add_middleware(cache_mw)
                return await p.run(context)
        
        result = benchmark.pedantic(run, rounds=1000, iterations=1)
        assert result.content == "test"

    def test_cache_hit_latency(self, benchmark, context):
        """Benchmark cache hit latency (subsequent requests)."""
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=1000)
        provider = EchoProvider(reply="cached")
        
        async def setup():
            # Warm up cache
            async with Pipeline(provider=provider) as p:
                p.add_middleware(cache_mw)
                await p.run(context)
            return cache_mw, provider
        
        async def run(prepared):
            cache_mw, provider = prepared
            async with Pipeline(provider=provider) as p:
                p.add_middleware(cache_mw)
                return await p.run(context)
        
        result = benchmark.pedantic(run, setup=setup, rounds=5000, iterations=1)
        assert result.content == "cached"

    def test_cache_throughput(self, benchmark, context):
        """Benchmark cache throughput (requests per second)."""
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=1000)
        provider = EchoProvider(reply="throughput test")
        
        async def run():
            async with Pipeline(provider=provider) as p:
                p.add_middleware(cache_mw)
                # First request to populate cache
                await p.run(context)
                # Subsequent requests from cache
                for _ in range(10):
                    await p.run(context)
        
        benchmark.pedantic(run, rounds=100, iterations=1)


class TestSyncApiBenchmarks:
    """Benchmarks for synchronous API performance."""

    def test_sync_run_latency(self, benchmark, context):
        """Benchmark sync run() method latency."""
        provider = EchoProvider(reply="sync test")
        
        def run():
            with Pipeline(provider=provider) as p:
                return p.run_sync(context)
        
        result = benchmark(run)
        assert result.content == "sync test"

    def test_sync_stream_latency(self, benchmark, context):
        """Benchmark sync stream() method latency."""
        provider = EchoProvider(reply="sync stream")
        
        def run():
            chunks = []
            with Pipeline(provider=provider) as p:
                for chunk in p.stream_sync(context):
                    if chunk.delta:
                        chunks.append(chunk.delta)
            return "".join(chunks)
        
        result = benchmark(run)
        assert "sync stream" in result

    def test_sync_vs_async_overhead(self, benchmark, context):
        """Compare sync vs async API overhead."""
        provider = EchoProvider(reply="comparison")
        
        # Async version
        async def async_run():
            async with Pipeline(provider=provider) as p:
                return await p.run(context)
        
        # Sync version
        def sync_run():
            with Pipeline(provider=provider) as p:
                return p.run_sync(context)
        
        # Benchmark both
        async_result = benchmark.pedantic(async_run, rounds=100, iterations=1)
        sync_result = benchmark(sync_run)
        
        assert async_result.content == sync_result.content


class TestMiddlewareStackBenchmarks:
    """Benchmarks for full middleware stack performance."""

    def test_full_stack_with_cache(self, benchmark, context):
        """Benchmark full middleware stack with caching enabled."""
        from onion_core.middlewares import (
            ContextWindowMiddleware,
            ObservabilityMiddleware,
            SafetyGuardrailMiddleware,
        )
        
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=100)
        provider = EchoProvider(reply="full stack")
        
        async def setup():
            p = Pipeline(provider=provider)
            p.add_middleware(ObservabilityMiddleware())
            p.add_middleware(SafetyGuardrailMiddleware())
            p.add_middleware(ContextWindowMiddleware(max_tokens=4000))
            p.add_middleware(cache_mw)
            async with p as pipeline:
                # Warm up cache
                await pipeline.run(context)
            return p
        
        async def run(pipeline):
            async with pipeline:
                return await pipeline.run(context)
        
        result = benchmark.pedantic(run, setup=setup, rounds=1000, iterations=1)
        assert result.content == "full stack"

    def test_concurrent_requests_with_cache(self, benchmark, context):
        """Benchmark concurrent requests with cache."""
        import asyncio
        
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=1000)
        provider = EchoProvider(reply="concurrent")
        
        async def run():
            async with Pipeline(provider=provider) as p:
                p.add_middleware(cache_mw)
                
                # Warm up cache
                await p.run(context)
                
                # Concurrent requests (all cache hits)
                tasks = [p.run(context) for _ in range(10)]
                return await asyncio.gather(*tasks)
        
        results = benchmark.pedantic(run, rounds=100, iterations=1)
        assert len(results) == 10


class TestMemoryEfficiencyBenchmarks:
    """Benchmarks for memory efficiency."""

    def test_cache_memory_usage(self, benchmark, context):
        """Benchmark cache memory usage with many entries."""
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=100)
        provider = EchoProvider(reply="memory test")
        
        async def run():
            async with Pipeline(provider=provider) as p:
                p.add_middleware(cache_mw)
                
                # Fill cache with different requests
                for i in range(100):
                    ctx = AgentContext(messages=[
                        Message(role="user", content=f"Request {i}")
                    ])
                    await p.run(ctx)
                
                return cache_mw.get_cache_size()
        
        cache_size = benchmark.pedantic(run, rounds=10, iterations=1)
        assert cache_size <= 100
