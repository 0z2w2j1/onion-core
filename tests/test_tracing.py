"""Tests for observability/tracing module."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, Message
from onion_core.models import FinishReason, LLMResponse, StreamChunk, ToolCall, ToolResult
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
        orig_meta = dict(context.metadata)
        await mw.on_error(context, ValueError("test error"))
        assert context.metadata == orig_meta

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


class TestTracingMiddlewareNoOpExtended:
    """Additional no-op tests for TracingMiddleware without OTel."""

    @pytest.mark.asyncio
    async def test_process_request_sets_otel_metadata(self, context):
        mw = TracingMiddleware(service_name="test", pipeline_name="test-pipeline")
        await mw.startup()
        result = await mw.process_request(context)
        assert result is context
        assert "_otel_span" in context.metadata
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_on_tool_call_stores_tool_span_metadata(self, context):
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        tool_call = ToolCall(id="tc-123", name="search", arguments={"query": "test"})
        result = await mw.on_tool_call(context, tool_call)
        assert result is tool_call
        key = f"_otel_tool_span_{tool_call.id}"
        assert key in context.metadata
        await mw.shutdown()


class TestTracingMiddlewareWithMetadata:

    @pytest.mark.asyncio
    async def test_process_response_cleans_metadata(self, context):
        """Test that process_response cleans up metadata."""
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        # Create a mock span that follows the protocol
        class MockSpan:
            def set_attribute(self, key: str, value) -> None: pass
            def set_status(self, status, description: str = "") -> None: pass
            def record_exception(self, error: Exception) -> None: pass
            def end(self) -> None: pass
        context.metadata["_otel_span"] = MockSpan()
        response = LLMResponse(content="test", model="gpt-4", finish_reason=FinishReason.STOP)
        await mw.process_response(context, response)
        assert "_otel_span" not in context.metadata
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_process_stream_chunk_with_finish_reason(self, context):
        """Test stream chunk processing with finish reason."""
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        class MockSpan:
            def set_attribute(self, key: str, value) -> None: pass
            def set_status(self, status, description: str = "") -> None: pass
            def record_exception(self, error: Exception) -> None: pass
            def end(self) -> None: pass
        context.metadata["_otel_span"] = MockSpan()
        chunk = StreamChunk(delta="", finish_reason=FinishReason.STOP)
        await mw.process_stream_chunk(context, chunk)
        assert "_otel_span" not in context.metadata
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_on_tool_call_with_mock_span(self, context):
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        class MockSpan:
            def set_attribute(self, key: str, value) -> None: pass
            def set_status(self, status, description: str = "") -> None: pass
            def record_exception(self, error: Exception) -> None: pass
            def end(self) -> None: pass
        tool_call = ToolCall(id="tc-123", name="search", arguments={"query": "test"})
        result = await mw.on_tool_call(context, tool_call)
        assert result is tool_call
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_on_tool_result_cleans_tool_span(self, context):
        """Test tool result cleans up tool span from metadata."""
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        class MockSpan:
            def set_attribute(self, key: str, value) -> None: pass
            def set_status(self, status, description: str = "") -> None: pass
            def record_exception(self, error: Exception) -> None: pass
            def end(self) -> None: pass
        context.metadata["_otel_tool_span_tc-123"] = MockSpan()
        result_in = ToolResult(tool_call_id="tc-123", name="search", result="ok")
        await mw.on_tool_result(context, result_in)
        assert "_otel_tool_span_tc-123" not in context.metadata
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_on_tool_result_with_error(self, context):
        """Test tool result with error status."""
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        class MockSpan:
            def set_attribute(self, key: str, value) -> None: pass
            def set_status(self, status, description: str = "") -> None: pass
            def record_exception(self, error: Exception) -> None: pass
            def end(self) -> None: pass
        context.metadata["_otel_tool_span_tc-456"] = MockSpan()
        result_in = ToolResult(tool_call_id="tc-456", name="calc", error="Division by zero")
        result = await mw.on_tool_result(context, result_in)
        assert result.is_error
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_on_error_clears_span(self, context):
        """Test error handler clears span from metadata."""
        mw = TracingMiddleware(service_name="test")
        await mw.startup()
        class MockSpan:
            def set_attribute(self, key: str, value) -> None: pass
            def set_status(self, status, description: str = "") -> None: pass
            def record_exception(self, error: Exception) -> None: pass
            def end(self) -> None: pass
        context.metadata["_otel_span"] = MockSpan()
        await mw.on_error(context, RuntimeError("test failure"))
        assert "_otel_span" not in context.metadata
        await mw.shutdown()

    @pytest.mark.asyncio
    async def test_full_lifecycle_integration(self, context):
        """Test complete middleware lifecycle."""
        mw = TracingMiddleware(service_name="integration-test", pipeline_name="main")
        await mw.startup()

        ctx = await mw.process_request(context)
        assert ctx is context

        response = LLMResponse(
            content="Hello",
            model="test-model",
            finish_reason=FinishReason.STOP
        )
        result = await mw.process_response(ctx, response)
        assert result is response
        assert "_otel_span" not in ctx.metadata

        await mw.on_error(ctx, ValueError("simulated error"))

        await mw.shutdown()