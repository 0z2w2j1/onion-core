"""中间件完整功能测试：Cache、RateLimit、Context等。"""

from __future__ import annotations

import asyncio

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline
from onion_core.middlewares.cache import ResponseCacheMiddleware
from onion_core.middlewares.context import ContextWindowMiddleware
from onion_core.middlewares.ratelimit import RateLimitMiddleware
from onion_core.models import FinishReason


def make_context(messages: list | None = None):
    """创建测试上下文。"""
    return AgentContext(
        messages=messages or [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


class TestResponseCacheMiddleware:
    """测试响应缓存中间件。"""

    @pytest.mark.asyncio
    async def test_cache_miss_then_hit(self):
        """缓存未命中后命中。"""
        provider = EchoProvider(reply="Cached response")
        cache_mw = ResponseCacheMiddleware(ttl_seconds=60)
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            # 第一次调用：缓存未命中
            ctx1 = make_context()
            resp1 = await pipeline.run(ctx1)
            assert cache_mw.misses == 1
            assert cache_mw.hits == 0

            # 第二次相同请求：缓存命中
            ctx2 = make_context()
            resp2 = await pipeline.run(ctx2)
            assert cache_mw.hits == 1
            assert cache_mw.misses == 1
            assert resp2.content == resp1.content

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self):
        """缓存TTL过期。"""
        provider = EchoProvider(reply="Expires soon")
        cache_mw = ResponseCacheMiddleware(ttl_seconds=0.1)  # 100ms TTL
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            # 第一次调用
            ctx1 = make_context()
            await pipeline.run(ctx1)
            assert cache_mw.misses == 1

            # 等待过期
            await asyncio.sleep(0.15)

            # 第二次调用：应过期
            ctx2 = make_context()
            await pipeline.run(ctx2)
            assert cache_mw.misses == 2  # 再次未命中

    @pytest.mark.asyncio
    async def test_different_messages_no_cache_hit(self):
        """不同消息不应命中缓存。"""
        provider = EchoProvider(reply="Different")
        cache_mw = ResponseCacheMiddleware()
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            # 第一个请求
            ctx1 = make_context([Message(role="user", content="Question 1")])
            await pipeline.run(ctx1)

            # 第二个不同请求
            ctx2 = make_context([Message(role="user", content="Question 2")])
            await pipeline.run(ctx2)

            assert cache_mw.misses == 2
            assert cache_mw.hits == 0

    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self):
        """LRU淘汰策略。"""
        provider = EchoProvider(reply="Evicted")
        cache_mw = ResponseCacheMiddleware(max_size=2)
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            # 填充缓存
            for i in range(3):
                ctx = make_context([Message(role="user", content=f"Q{i}")])
                await pipeline.run(ctx)

            # 缓存大小不应超过max_size
            assert cache_mw.get_cache_size() <= 2

    @pytest.mark.asyncio
    async def test_cache_hit_rate(self):
        """缓存命中率计算。"""
        provider = EchoProvider(reply="Hit rate test")
        cache_mw = ResponseCacheMiddleware()
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            # 2次未命中（不同消息）
            for i in range(2):
                ctx = make_context([Message(role="user", content=f"Q{i}")])
                await pipeline.run(ctx)

            # 2次命中（重复相同请求）
            ctx = make_context([Message(role="user", content="Repeat")])
            await pipeline.run(ctx)  # 第3次调用，未命中
            await pipeline.run(ctx)  # 第4次调用，命中

            # 总共4次调用：3次未命中 + 1次命中
            assert cache_mw.hit_rate == 0.25  # 1/4 = 25%

    @pytest.mark.asyncio
    async def test_cache_clear(self):
        """清空缓存。"""
        provider = EchoProvider(reply="Clear test")
        cache_mw = ResponseCacheMiddleware()
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            ctx = make_context()
            await pipeline.run(ctx)
            
            assert cache_mw.get_cache_size() > 0
            
            cache_mw.clear_cache()
            assert cache_mw.get_cache_size() == 0

    @pytest.mark.asyncio
    async def test_only_cache_stop_responses(self):
        """仅缓存finish_reason为stop的响应。"""
        
        class ToolCallProvider(EchoProvider):
            async def complete(self, context: AgentContext) -> LLMResponse:
                return LLMResponse(
                    content="Tool call",
                    finish_reason=FinishReason.TOOL_CALLS,
                )
        
        provider = ToolCallProvider()
        cache_mw = ResponseCacheMiddleware()
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            ctx = make_context()
            await pipeline.run(ctx)
            
            # 工具调用响应不应被缓存
            assert cache_mw.get_cache_size() == 0

    def test_cache_key_strategy_user_only(self):
        """用户消息-only缓存键策略。"""
        cache_mw = ResponseCacheMiddleware(cache_key_strategy="user_only")
        
        ctx1 = AgentContext(messages=[
            Message(role="system", content="System message"),
            Message(role="user", content="User question"),
        ])
        
        ctx2 = AgentContext(messages=[
            Message(role="system", content="Different system"),
            Message(role="user", content="User question"),  # 相同用户消息
        ])
        
        key1 = cache_mw._generate_cache_key(ctx1)
        key2 = cache_mw._generate_cache_key(ctx2)
        
        # user_only策略下，系统消息不同但用户消息相同应产生相同key
        assert key1 == key2

    def test_cache_key_strategy_full(self):
        """完整缓存键策略。"""
        cache_mw = ResponseCacheMiddleware(cache_key_strategy="full")
        
        ctx1 = AgentContext(messages=[
            Message(role="system", content="System A"),
            Message(role="user", content="User question"),
        ])
        
        ctx2 = AgentContext(messages=[
            Message(role="system", content="System B"),
            Message(role="user", content="User question"),
        ])
        
        key1 = cache_mw._generate_cache_key(ctx1)
        key2 = cache_mw._generate_cache_key(ctx2)
        
        # full策略下，系统消息不同应产生不同key
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_stream_not_cached(self):
        """流式响应不被缓存。"""
        provider = EchoProvider(reply="Stream test")
        cache_mw = ResponseCacheMiddleware()
        
        pipeline = Pipeline(provider=provider).add_middleware(cache_mw)

        async with pipeline:
            ctx = make_context()
            chunks = []
            async for chunk in pipeline.stream(ctx):
                chunks.append(chunk)
            
            # 流式响应不应被缓存
            assert cache_mw.get_cache_size() == 0


class TestContextWindowMiddleware:
    """测试上下文窗口中间件。"""

    @pytest.mark.asyncio
    async def test_context_truncation(self):
        """超长上下文裁剪。"""
        provider = EchoProvider(reply="Truncated")
        context_mw = ContextWindowMiddleware(max_tokens=100, keep_rounds=1)
        
        pipeline = Pipeline(provider=provider).add_middleware(context_mw)

        # 创建超长上下文
        messages = [Message(role="system", content="System")]
        for i in range(20):
            messages.append(Message(role="user", content=f"Round {i}: " + "word " * 50))
            messages.append(Message(role="assistant", content="Response " * 50))
        
        ctx = AgentContext(messages=messages)

        async with pipeline:
            await pipeline.run(ctx)
            
            # 验证上下文被裁剪
            assert ctx.metadata.get("context_truncated") is True
            assert len(ctx.messages) < len(messages)

    @pytest.mark.asyncio
    async def test_context_within_limit(self):
        """上下文在限制内不裁剪。"""
        provider = EchoProvider(reply="Within limit")
        context_mw = ContextWindowMiddleware(max_tokens=10000)
        
        pipeline = Pipeline(provider=provider).add_middleware(context_mw)

        ctx = make_context()

        async with pipeline:
            await pipeline.run(ctx)
            
            assert ctx.metadata.get("context_truncated") is False

    @pytest.mark.asyncio
    async def test_keep_system_message(self):
        """保留系统消息。"""
        provider = EchoProvider(reply="Keep system")
        context_mw = ContextWindowMiddleware(max_tokens=50, keep_rounds=0)
        
        pipeline = Pipeline(provider=provider).add_middleware(context_mw)

        messages = [
            Message(role="system", content="Important system instruction"),
            Message(role="user", content="User " * 100),
        ]
        ctx = AgentContext(messages=messages)

        async with pipeline:
            await pipeline.run(ctx)
            
            # 系统消息应始终保留
            assert any(msg.role == "system" for msg in ctx.messages)

    @pytest.mark.asyncio
    async def test_custom_encoding(self):
        """自定义编码名称。"""
        provider = EchoProvider(reply="Custom encoding")
        context_mw = ContextWindowMiddleware(
            max_tokens=100,
            encoding_name="cl100k_base",  # GPT-4 encoding
        )
        
        pipeline = Pipeline(provider=provider).add_middleware(context_mw)

        ctx = make_context()

        async with pipeline:
            # 不应抛出异常
            await pipeline.run(ctx)


class TestRateLimitMiddleware:
    """测试限流中间件。"""

    @pytest.mark.asyncio
    async def test_rate_limit_allows_within_quota(self):
        """配额内允许通过。"""
        provider = EchoProvider(reply="Allowed")
        rate_limit_mw = RateLimitMiddleware(
            max_requests=10,
            window_seconds=60,
        )
        
        pipeline = Pipeline(provider=provider).add_middleware(rate_limit_mw)

        async with pipeline:
            for _ in range(5):
                ctx = make_context()
                response = await pipeline.run(ctx)
                assert response.content

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_exceeded(self):
        """超出配额时阻止。"""
        from onion_core.models import RateLimitExceeded
        
        provider = EchoProvider(reply="Should not reach")
        rate_limit_mw = RateLimitMiddleware(
            max_requests=2,
            window_seconds=60,
        )
        
        pipeline = Pipeline(provider=provider).add_middleware(rate_limit_mw)

        async with pipeline:
            # 前2次应成功（使用相同的session_id）
            ctx = make_context()
            for _ in range(2):
                await pipeline.run(ctx)
            
            # 第3次应被限流
            with pytest.raises(RateLimitExceeded):
                await pipeline.run(ctx)

    @pytest.mark.asyncio
    async def test_rate_limit_window_reset(self):
        """时间窗口重置。"""
        provider = EchoProvider(reply="After reset")
        rate_limit_mw = RateLimitMiddleware(
            max_requests=1,
            window_seconds=0.1,  # 100ms窗口
        )
        
        pipeline = Pipeline(provider=provider).add_middleware(rate_limit_mw)

        async with pipeline:
            # 第一次调用
            ctx = make_context()
            await pipeline.run(ctx)
            
            # 等待窗口重置
            await asyncio.sleep(0.15)
            
            # 应允许新的请求（相同的session_id）
            response = await pipeline.run(ctx)
            assert response.content

    @pytest.mark.asyncio
    async def test_rate_limit_per_session(self):
        """按session_id限流。"""
        from onion_core.models import RateLimitExceeded
        
        provider = EchoProvider(reply="Per session")
        rate_limit_mw = RateLimitMiddleware(
            max_requests=1,
            window_seconds=60,
        )
        
        pipeline = Pipeline(provider=provider).add_middleware(rate_limit_mw)

        async with pipeline:
            # Session 1
            ctx1 = AgentContext(
                messages=[Message(role="user", content="Test")],
                session_id="session_1",
            )
            await pipeline.run(ctx1)
            
            # Session 1 再次调用应被限流
            with pytest.raises(RateLimitExceeded):
                await pipeline.run(ctx1)
            
            # Session 2 应允许
            ctx2 = AgentContext(
                messages=[Message(role="user", content="Test")],
                session_id="session_2",
            )
            response = await pipeline.run(ctx2)
            assert response.content


class TestSafetyMiddlewareAdvanced:
    """测试 SafetyGuardrailMiddleware 高级功能。"""

    @pytest.mark.asyncio
    async def test_streaming_pii_masking_buffer_boundary(self):
        """Test streaming PII masking at buffer boundary."""
        from onion_core.middlewares.safety import SafetyGuardrailMiddleware
        from onion_core.models import StreamChunk
        
        middleware = SafetyGuardrailMiddleware()
        
        # Create a phone number that spans the buffer boundary (50 chars)
        prefix = "a" * 45  # 45 chars
        phone = "13812345678"  # 11 chars, total 56 > 50
        
        ctx = AgentContext(messages=[Message(role="user", content="test")])
        
        # First chunk fills buffer
        chunk1 = StreamChunk(delta=prefix, index=0)
        result1 = await middleware.process_stream_chunk(ctx, chunk1)
        assert result1.delta == ""  # Buffered, not output yet
        
        # Second chunk completes the phone number
        chunk2 = StreamChunk(delta=phone, index=1)
        result2 = await middleware.process_stream_chunk(ctx, chunk2)
        # Should mask the phone number in the safe prefix
        assert "13812345678" not in result2.delta
        
        # Finish the stream
        chunk3 = StreamChunk(delta="", index=2, finish_reason="stop")
        result3 = await middleware.process_stream_chunk(ctx, chunk3)
        assert "13812345678" not in result3.delta

    @pytest.mark.asyncio
    async def test_add_blocked_keyword_dynamic(self):
        """Test dynamically adding blocked keywords."""
        from onion_core.middlewares.safety import SafetyGuardrailMiddleware
        from onion_core.models import SecurityException
        
        middleware = SafetyGuardrailMiddleware(blocked_keywords=[])
        middleware.add_blocked_keyword("custom-block-word")
        
        ctx = AgentContext(
            messages=[Message(role="user", content="Please custom-block-word this")]
        )
        
        with pytest.raises(SecurityException):
            await middleware.process_request(ctx)

    @pytest.mark.asyncio
    async def test_add_blocked_tool_dynamic(self):
        """Test dynamically adding blocked tools."""
        from onion_core.middlewares.safety import SafetyGuardrailMiddleware
        from onion_core.models import SecurityException, ToolCall
        
        middleware = SafetyGuardrailMiddleware(blocked_tools=[])
        middleware.add_blocked_tool("dangerous_tool")
        
        ctx = AgentContext(messages=[Message(role="user", content="test")])
        tool_call = ToolCall(id="1", name="dangerous_tool", arguments={})
        
        with pytest.raises(SecurityException, match="dangerous_tool"):
            await middleware.on_tool_call(ctx, tool_call)

    @pytest.mark.asyncio
    async def test_add_pii_rule_dynamic(self):
        """Test dynamically adding custom PII rules."""
        import re

        from onion_core.middlewares.safety import PiiRule, SafetyGuardrailMiddleware
        
        custom_rule = PiiRule(
            name="custom_secret",
            pattern=re.compile(r"SECRET-\d{4}"),
            replacement="[REDACTED]",
        )
        
        middleware = SafetyGuardrailMiddleware(enable_builtin_pii=False)
        middleware.add_pii_rule(custom_rule)
        
        ctx = AgentContext(messages=[Message(role="user", content="test")])
        response = LLMResponse(content="My code is SECRET-1234")
        
        result = await middleware.process_response(ctx, response)
        assert result.content == "My code is [REDACTED]"


