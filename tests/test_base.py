"""Tests for base middleware and Provider integration."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.base import BaseMiddleware
from onion_core.middlewares import ObservabilityMiddleware
from onion_core.provider import LLMProvider


class TestProvider:
    """Test LLMProvider abstract class."""

    def test_provider_attribute(self):
        class TestProvider(LLMProvider):
            async def complete(self, ctx): pass
            def stream(self, ctx): pass

        provider = TestProvider()
        assert hasattr(provider, 'complete')
        assert hasattr(provider, 'stream')


class TestMiddlewareInheritance:
    """Test concrete middleware inheritance."""

    @pytest.mark.asyncio
    async def test_middleware_integration(self):
        context = AgentContext(messages=[Message(role="user", content="test")])
        provider = EchoProvider(reply="success")
        pipeline = Pipeline(provider=provider)
        pipeline.add_middleware(ObservabilityMiddleware())

        async with pipeline:
            result = await pipeline.run(context)
            assert result.content == "success"


class _ConcreteMiddleware(BaseMiddleware):
    """Concrete subclass for testing default implementations."""

    async def process_request(self, ctx):
        return ctx

    async def process_response(self, ctx, r):
        return r

    async def process_stream_chunk(self, ctx, c):
        return c

    async def on_tool_call(self, ctx, tc):
        return tc

    async def on_tool_result(self, ctx, r):
        return r

    async def on_error(self, ctx, e):
        pass


class TestBaseMiddlewareDefaults:
    """Test BaseMiddleware default method implementations."""

    @pytest.fixture
    def mw(self):
        return _ConcreteMiddleware()

    @pytest.mark.asyncio
    async def test_default_stream_chunk_passthrough(self, mw):
        from onion_core import StreamChunk
        ctx = AgentContext(messages=[Message(role="user", content="test")])
        chunk = StreamChunk(delta="hello")
        result = await mw.process_stream_chunk(ctx, chunk)
        assert result is chunk

    @pytest.mark.asyncio
    async def test_default_tool_call_passthrough(self, mw):
        from onion_core import ToolCall
        ctx = AgentContext(messages=[Message(role="user", content="test")])
        tc = ToolCall(id="t1", name="test", arguments={})
        result = await mw.on_tool_call(ctx, tc)
        assert result is tc

    @pytest.mark.asyncio
    async def test_default_tool_result_passthrough(self, mw):
        from onion_core import ToolResult
        ctx = AgentContext(messages=[Message(role="user", content="test")])
        tr = ToolResult(tool_call_id="t1", name="test", result="ok")
        result = await mw.on_tool_result(ctx, tr)
        assert result is tr

    @pytest.mark.asyncio
    async def test_default_on_error_noop(self, mw):
        ctx = AgentContext(messages=[Message(role="user", content="test")])
        await mw.on_error(ctx, RuntimeError("test"))

    @pytest.mark.asyncio
    async def test_default_startup_shutdown(self, mw):
        await mw.startup()
        await mw.shutdown()

    def test_name_property(self, mw):
        assert "Concrete" in mw.name