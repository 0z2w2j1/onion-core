"""
Onion Core - OpenTelemetry 集成

为 Pipeline 提供分布式追踪支持。每次 run()/stream() 调用创建一个 span，
request_id 作为 trace attribute 传播，工具调用创建子 span。

依赖（可选）：
    pip install opentelemetry-api opentelemetry-sdk

若未安装 opentelemetry，所有操作退化为 no-op，不影响正常运行。

用法：
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    from onion_core.observability.tracing import TracingMiddleware
    pipeline.add_middleware(TracingMiddleware(service_name="my-agent"))
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.tracing")


@runtime_checkable
class SpanLike(Protocol):
    def set_attribute(self, key: str, value: str | int) -> None: ...
    def set_status(self, status: object) -> None: ...
    def record_exception(self, error: Exception) -> None: ...
    def end(self) -> None: ...
    def __enter__(self) -> SpanLike: ...
    def __exit__(self, *a: object) -> None: ...


@runtime_checkable
class TracerLike(Protocol):
    def start_span(self, name: str) -> SpanLike: ...


class _NoOpSpan:
    def set_attribute(self, *a, **kw): pass
    def set_status(self, *a, **kw): pass
    def record_exception(self, *a, **kw): pass
    def end(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass


TracersType = TracerLike | None


class TracingMiddleware(BaseMiddleware):
    """
    OpenTelemetry 追踪中间件。priority=50（最外层，包裹所有其他中间件）。

    每次 run()/stream() 调用创建一个根 span：
      - span name: "onion.request"
      - attributes: pipeline_name, request_id, session_id, message_count, model
    工具调用创建子 span：
      - span name: "onion.tool.<tool_name>"
    """

    priority: int = 50

    def __init__(self, service_name: str = "onion-core", pipeline_name: str = "default") -> None:
        self._service_name = service_name
        self._pipeline_name = pipeline_name
        self._tracer: TracersType = None
        self._otel_available = False

    async def startup(self) -> None:
        try:
            from opentelemetry import trace as otel_trace
            from opentelemetry.trace import StatusCode
            self._tracer = otel_trace.get_tracer(self._service_name)
            self._otel_status_code = StatusCode
            self._otel_available = True
            logger.info("TracingMiddleware started (OpenTelemetry available) | pipeline=%s.",
                        self._pipeline_name)
        except ImportError:
            self._otel_available = False
            logger.warning(
                "TracingMiddleware started but opentelemetry-api is not installed. "
                "Tracing is disabled. Install with: pip install opentelemetry-api opentelemetry-sdk"
            )

    async def shutdown(self) -> None:
        logger.info("TracingMiddleware stopped.")

    async def process_request(self, context: AgentContext) -> AgentContext:
        if not self._otel_available or self._tracer is None:
            return context

        span = self._tracer.start_span("onion.request")
        span.set_attribute("onion.pipeline_name", self._pipeline_name)
        span.set_attribute("onion.request_id", context.request_id)
        span.set_attribute("onion.session_id", context.session_id)
        span.set_attribute("onion.message_count", len(context.messages))

        context.metadata["_otel_span"] = span
        return context

    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        span: SpanLike | None = context.metadata.pop("_otel_span", None)
        if span is None:
            return response

        if response.model:
            span.set_attribute("onion.model", response.model)
        if response.finish_reason:
            span.set_attribute("onion.finish_reason", response.finish_reason)
        if response.usage:
            span.set_attribute("onion.tokens.total", response.usage.total_tokens)
            span.set_attribute("onion.tokens.prompt", response.usage.prompt_tokens)
            span.set_attribute("onion.tokens.completion", response.usage.completion_tokens)

        span.set_status(self._otel_status_code.OK)
        span.end()
        return response

    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk:
        if chunk.finish_reason:
            span: SpanLike | None = context.metadata.pop("_otel_span", None)
            if span is not None:
                span.set_attribute("onion.finish_reason", chunk.finish_reason)
                span.set_status(self._otel_status_code.OK)
                span.end()
        return chunk

    async def on_tool_call(
        self, context: AgentContext, tool_call: ToolCall
    ) -> ToolCall:
        if not self._otel_available or self._tracer is None:
            return tool_call

        span = self._tracer.start_span(f"onion.tool.{tool_call.name}")
        span.set_attribute("onion.pipeline_name", self._pipeline_name)
        span.set_attribute("onion.tool.id", tool_call.id)
        span.set_attribute("onion.tool.name", tool_call.name)
        context.metadata[f"_otel_tool_span_{tool_call.id}"] = span
        return tool_call

    async def on_tool_result(
        self, context: AgentContext, result: ToolResult
    ) -> ToolResult:
        span: SpanLike | None = context.metadata.pop(f"_otel_tool_span_{result.tool_call_id}", None)
        if span is not None:
            if result.is_error:
                span.set_attribute("onion.tool.error", result.error or "unknown")
                span.set_status(self._otel_status_code.ERROR)
            else:
                span.set_status(self._otel_status_code.OK)
            span.end()
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        span: SpanLike | None = context.metadata.pop("_otel_span", None)
        if span is not None:
            span.record_exception(error)
            span.set_status(self._otel_status_code.ERROR, str(error))
            span.end()
