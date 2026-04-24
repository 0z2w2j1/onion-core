"""ResponseCacheMiddleware 测试。"""

from __future__ import annotations

import asyncio

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline
from onion_core.middlewares import ResponseCacheMiddleware

from .conftest import make_context


@pytest.fixture
def cache_middleware():
    """创建缓存中间件。"""
    return ResponseCacheMiddleware(ttl_seconds=1.0, max_size=10)


@pytest.fixture
async def cached_pipeline(cache_middleware):
    """创建带缓存的 Pipeline。"""
    p = Pipeline(provider=EchoProvider(reply="cached response"))
    p.add_middleware(cache_middleware)
    async with p as pipeline:
        yield pipeline, cache_middleware


class TestResponseCacheMiddleware:
    """测试响应缓存中间件。"""

    @pytest.mark.asyncio
    async def test_cache_miss_then_hit(self, cached_pipeline):
        """测试首次未命中，第二次命中。"""
        pipeline, cache_mw = cached_pipeline
        
        # 第一次请求（缓存未命中）
        ctx1 = make_context()
        resp1 = await pipeline.run(ctx1)
        assert resp1.content == "cached response"
        assert cache_mw.misses == 1
        assert cache_mw.hits == 0
        
        # 第二次相同请求（缓存命中）
        ctx2 = make_context()
        resp2 = await pipeline.run(ctx2)
        assert resp2.content == "cached response"
        assert cache_mw.hits == 1
        assert cache_mw.misses == 1

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self, cached_pipeline):
        """测试缓存 TTL 过期。"""
        pipeline, cache_mw = cached_pipeline
        
        # 第一次请求
        ctx1 = make_context()
        await pipeline.run(ctx1)
        assert cache_mw.misses == 1
        
        # 等待 TTL 过期
        await asyncio.sleep(1.1)
        
        # 第二次请求（应未命中）
        ctx2 = make_context()
        await pipeline.run(ctx2)
        assert cache_mw.misses == 2
        assert cache_mw.hits == 0

    @pytest.mark.asyncio
    async def test_different_messages_no_cache_hit(self, cached_pipeline):
        """测试不同消息不会命中缓存。"""
        pipeline, cache_mw = cached_pipeline
        
        # 第一个请求
        ctx1 = AgentContext(messages=[Message(role="user", content="Hello")])
        await pipeline.run(ctx1)
        
        # 第二个不同请求
        ctx2 = AgentContext(messages=[Message(role="user", content="World")])
        await pipeline.run(ctx2)
        
        # 两次都应未命中
        assert cache_mw.misses == 2
        assert cache_mw.hits == 0

    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self):
        """测试 LRU 淘汰策略。"""
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60.0, max_size=3)
        p = Pipeline(provider=EchoProvider())
        p.add_middleware(cache_mw)
        
        async with p as pipeline:
            # 填充缓存到最大容量
            for i in range(3):
                ctx = AgentContext(messages=[Message(role="user", content=f"msg{i}")])
                await pipeline.run(ctx)
            
            assert cache_mw.get_cache_size() == 3
            
            # 添加第4个，应淘汰最旧的
            ctx_new = AgentContext(messages=[Message(role="user", content="msg_new")])
            await pipeline.run(ctx_new)
            
            assert cache_mw.get_cache_size() == 3

    @pytest.mark.asyncio
    async def test_cache_hit_rate(self, cached_pipeline):
        """测试命中率计算。"""
        pipeline, cache_mw = cached_pipeline
        
        # 初始命中率为 0
        assert cache_mw.hit_rate == 0.0
        
        # 第一次请求（未命中）
        ctx1 = make_context()
        await pipeline.run(ctx1)
        assert cache_mw.hit_rate == 0.0
        
        # 第二次相同请求（命中）
        ctx2 = make_context()
        await pipeline.run(ctx2)
        assert cache_mw.hit_rate == 0.5  # 1 hit / 2 total

    @pytest.mark.asyncio
    async def test_cache_clear(self, cached_pipeline):
        """测试清空缓存。"""
        pipeline, cache_mw = cached_pipeline
        
        # 填充缓存
        ctx = make_context()
        await pipeline.run(ctx)
        assert cache_mw.get_cache_size() > 0
        
        # 清空
        cache_mw.clear_cache()
        assert cache_mw.get_cache_size() == 0

    @pytest.mark.asyncio
    async def test_only_cache_stop_responses(self, cached_pipeline):
        """测试仅缓存 finish_reason='stop' 的响应。"""
        from unittest.mock import AsyncMock, MagicMock
        
        pipeline, cache_mw = cached_pipeline
        
        # 模拟一个非 stop 的响应
        mock_provider = MagicMock()
        mock_response = LLMResponse(
            content="test",
            finish_reason="tool_calls",
            model="test-model",
        )
        mock_provider.complete = AsyncMock(return_value=mock_response)
        mock_provider.name = "MockProvider"
        
        p = Pipeline(provider=mock_provider)
        p.add_middleware(cache_mw)
        
        async with p as pl:
            ctx = make_context()
            await pl.run(ctx)
            
            # 不应缓存 tool_calls 响应
            assert cache_mw.get_cache_size() == 0

    def test_cache_key_strategy_user_only(self):
        """测试 user_only 缓存键策略。"""
        mw = ResponseCacheMiddleware(cache_key_strategy="user_only")
        
        ctx1 = AgentContext(messages=[
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ])
        
        ctx2 = AgentContext(messages=[
            Message(role="system", content="Different system"),
            Message(role="user", content="Hello"),
        ])
        
        # user_only 策略下，两个上下文应有相同的缓存键
        key1 = mw._generate_cache_key(ctx1)
        key2 = mw._generate_cache_key(ctx2)
        assert key1 == key2

    def test_cache_key_strategy_full(self):
        """测试 full 缓存键策略。"""
        mw = ResponseCacheMiddleware(cache_key_strategy="full")
        
        ctx1 = AgentContext(messages=[
            Message(role="system", content="System A"),
            Message(role="user", content="Hello"),
        ])
        
        ctx2 = AgentContext(messages=[
            Message(role="system", content="System B"),
            Message(role="user", content="Hello"),
        ])
        
        # full 策略下，两个上下文应有不同的缓存键
        key1 = mw._generate_cache_key(ctx1)
        key2 = mw._generate_cache_key(ctx2)
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_stream_not_cached(self):
        """测试流式响应不被缓存。"""
        cache_mw = ResponseCacheMiddleware()
        p = Pipeline(provider=EchoProvider())
        p.add_middleware(cache_mw)
        
        async with p as pipeline:
            ctx = make_context()
            chunks = []
            async for chunk in pipeline.stream(ctx):
                chunks.append(chunk)
            
            # 流式响应不应被缓存
            assert cache_mw.get_cache_size() == 0
