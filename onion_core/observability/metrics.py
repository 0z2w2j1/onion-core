"""
Onion Core - Prometheus 指标

为 Pipeline 提供延迟直方图、请求计数器、Token 用量统计。

依赖（可选）：
    pip install prometheus-client

若未安装，所有操作退化为 no-op。

用法：
    from onion_core.observability.metrics import MetricsMiddleware
    pipeline.add_middleware(MetricsMiddleware(pipeline_name="my-agent"))

    # 暴露 /metrics 端点（需自行集成 HTTP server）
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
"""

from __future__ import annotations

import logging
import time

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.metrics")

try:
    from prometheus_client import Counter, Histogram
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False


def _make_counter(name, desc, labels):
    if _PROM_AVAILABLE:
        return Counter(name, desc, labels)
    return _NoOpMetric()


def _make_histogram(name, desc, labels, buckets=None):
    if _PROM_AVAILABLE:
        kwargs = {"buckets": buckets} if buckets else {}
        return Histogram(name, desc, labels, **kwargs)
    return _NoOpMetric()


class _NoOpMetric:
    def labels(self, **kw): return self
    def inc(self, *a): pass
    def observe(self, *a): pass
    def set(self, *a): pass
    def dec(self, *a): pass


# ── 全局指标（模块级单例，避免重复注册）────────────────────────────────────────
# 所有指标强制包含 pipeline_name 标签

_REQUEST_TOTAL = _make_counter(
    "onion_requests_total",
    "Total number of pipeline requests",
    ["pipeline_name", "model", "finish_reason", "status"],
)

_REQUEST_LATENCY = _make_histogram(
    "onion_request_duration_seconds",
    "Pipeline request latency in seconds",
    ["pipeline_name", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

_TOKEN_USAGE = _make_counter(
    "onion_tokens_total",
    "Total tokens consumed",
    ["pipeline_name", "model", "type"],  # values: prompt, completion
)

_TOOL_CALLS_TOTAL = _make_counter(
    "onion_tool_calls_total",
    "Total tool calls",
    ["pipeline_name", "tool_name", "status"],  # status: ok | error | blocked
)

_ACTIVE_REQUESTS = _NoOpMetric()
if _PROM_AVAILABLE:
    from prometheus_client import Gauge as _Gauge
    _ACTIVE_REQUESTS = _Gauge(
        "onion_active_requests",
        "Number of requests currently being processed",
        ["pipeline_name"],
    )


class MetricsMiddleware(BaseMiddleware):
    """
    Prometheus 指标中间件。priority=90（紧跟 TracingMiddleware 之后）。

    所有指标均携带 pipeline_name 标签，便于多 Pipeline 实例区分。

    指标：
      onion_requests_total{pipeline_name, model, finish_reason, status}
      onion_request_duration_seconds{pipeline_name, model}
      onion_tokens_total{pipeline_name, model, type}
      onion_tool_calls_total{pipeline_name, tool_name, status}
      onion_active_requests{pipeline_name}
    """

    priority: int = 90

    def __init__(self, pipeline_name: str = "default") -> None:
        self._pipeline_name = pipeline_name

    async def startup(self) -> None:
        if _PROM_AVAILABLE:
            logger.info("MetricsMiddleware started (prometheus-client available) | pipeline=%s.",
                        self._pipeline_name)
        else:
            logger.warning(
                "MetricsMiddleware started but prometheus-client is not installed. "
                "Metrics are disabled. Install with: pip install prometheus-client"
            )

    async def shutdown(self) -> None:
        logger.info("MetricsMiddleware stopped.")

    async def process_request(self, context: AgentContext) -> AgentContext:
        context.metadata["_metrics_start"] = time.perf_counter()
        _ACTIVE_REQUESTS.labels(pipeline_name=self._pipeline_name).inc()
        return context

    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        self._record_completion(context, response.model or "unknown", response.finish_reason or "unknown", "ok")
        if response.usage:
            model = response.model or "unknown"
            _TOKEN_USAGE.labels(pipeline_name=self._pipeline_name, model=model, type="prompt").inc(response.usage.prompt_tokens)
            _TOKEN_USAGE.labels(pipeline_name=self._pipeline_name, model=model, type="completion").inc(response.usage.completion_tokens)
        return response

    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk:
        if chunk.finish_reason:
            self._record_completion(context, "stream", chunk.finish_reason, "ok")
        return chunk

    async def on_tool_call(
        self, context: AgentContext, tool_call: ToolCall
    ) -> ToolCall:
        context.metadata[f"_tool_start_{tool_call.id}"] = time.perf_counter()
        return tool_call

    async def on_tool_result(
        self, context: AgentContext, result: ToolResult
    ) -> ToolResult:
        status = "error" if result.is_error else "ok"
        _TOOL_CALLS_TOTAL.labels(
            pipeline_name=self._pipeline_name, tool_name=result.name, status=status
        ).inc()
        context.metadata.pop(f"_tool_start_{result.tool_call_id}", None)
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        self._record_completion(context, "unknown", "error", "error")

    def _record_completion(
        self, context: AgentContext, model: str, finish_reason: str, status: str
    ) -> None:
        if _PROM_AVAILABLE:
            _ACTIVE_REQUESTS.labels(pipeline_name=self._pipeline_name).dec()
        start = context.metadata.pop("_metrics_start", None)
        if start is not None:
            duration = time.perf_counter() - start
            _REQUEST_LATENCY.labels(pipeline_name=self._pipeline_name, model=model).observe(duration)
        _REQUEST_TOTAL.labels(
            pipeline_name=self._pipeline_name,
            model=model,
            finish_reason=finish_reason,
            status=status,
        ).inc()
