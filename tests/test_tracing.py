"""Tests for observability/tracing module."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, Message
from onion_core.models import LLMResponse, StreamChunk, ToolCall, ToolResult, FinishReason
from onion_core.observability.tracing import TracingMiddleware


@pytest.fixture
def context():
    return AgentContext(
        messages=[
            Message(role="user", content="test"),
        ]
    )


class TestTracingMiddlewareNoOp:
    """Test TracingMiddleware when OpenTelemetry is not available."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        pytest.importorskip("opentelemetry") is not None,
        reason="OpenTelemetry is installed in CI"
    )
    async def test_startup_without_otel(self, context):
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        assert not mw._otel_available
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_process_request_without_otel(self, context):
        mw = TracingMiddleware(service_name="test")
        result = await mw.process_request(context)
        assert result is context

    @pytest.mark.asyncio
    async def test_process_response_without_otel(self, context):
        mw = TracingMiddleware(service_name="test")
        response = LLMResponse(content="test", model="gpt-4")
        result = await mw.process_response(context, response)
        assert result is response

    @pytest.mark.asyncio
    async def test_process_stream_chunk_without_otel(self, context):
        mw = TracingMiddleware(service_name="test")
        chunk = StreamChunk(delta="hello", finish_reason=FinishReason.STOP)
        result = await mw.process_stream_chunk(context, chunk)
        assert result is chunk

    @pytest.mark.asyncio
    async def test_on_tool_call_without_otel(self, context):
        mw = TracingMiddleware(service_name="test")
        tool_call = ToolCall(id="1", name="test_tool", arguments={})
        result = await mw.on_tool_call(context, tool_call)
        assert result is tool_call

    @pytest.mark.asyncio
    async def test_on_tool_result_without_otel(self, context):
        mw = TracingMiddleware(service_name="test")
        result_in = ToolResult(tool_call_id="1", name="test", result="ok")
        result = await mw.on_tool_result(context, result_in)
        assert result is result_in

    @pytest.mark.asyncio
    async def test_on_error_without_otel(self, context):
        mw = TracingMiddleware(service_name="test")
        await mw.on_error(context, ValueError("test error"))

    @pytest.mark.asyncio
    async def test_priority_is_50(self):
        mw = TracingMiddleware(service_name="test")
        assert mw.priority == 50


class TestProtocols:
    def test_span_like_protocol(self):
        from onion_core.observability.tracing import SpanLike

        class DummySpan:
            def set_attribute(self, key: str, value: str | int) -> None: pass
            def set_status(self, status: object) -> None: pass
            def record_exception(self, error: Exception) -> None: pass
            def end(self) -> None: pass
            def __enter__(self): return self
            def __exit__(self, *a: object) -> None: pass

        span = DummySpan()
        assert isinstance(span, SpanLike)

    def test_tracer_like_protocol(self):
        from onion_core.observability.tracing import TracerLike

        class DummyTracer:
            def start_span(self, name: str):
                class DummySpan:
                    pass
                return DummySpan()

        tracer = DummyTracer()
        assert isinstance(tracer, TracerLike)