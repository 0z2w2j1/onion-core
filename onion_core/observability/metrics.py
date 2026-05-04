"""
Onion Core - Prometheus 指标

为 Pipeline 提供延迟直方图、请求计数器、Token 用量统计、成本追踪。

依赖（可选）：
    pip install prometheus-client

若未安装，所有操作退化为 no-op。

用法：
    from onion_core.observability.metrics import MetricsMiddleware
    pipeline.add_middleware(MetricsMiddleware(pipeline_name="my-agent"))

    # 暴露 /metrics 端点（需自行集成 HTTP server）
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
增强功能（v0.9.0）：
    - Token 成本追踪（onion_token_cost_usd）
    - P95/P99 延迟百分位监控（Summary 指标）
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.metrics")

try:
    from prometheus_client import Counter as _PromCounter, Histogram as _PromHistogram, Summary as _PromSummary
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False


def _make_counter(name: str, desc: str, labels: list[str]) -> _PromCounter | _NoOpMetric:
    if _PROM_AVAILABLE:
        return _PromCounter(name, desc, labels)
    return _NoOpMetric()


def _make_histogram(name: str, desc: str, labels: list[str], buckets: list[float] | None = None) -> _PromHistogram | _NoOpMetric:
    if _PROM_AVAILABLE:
        kwargs: dict[str, Any] = {"buckets": buckets} if buckets else {}
        return _PromHistogram(name, desc, labels, **kwargs)
    return _NoOpMetric()


class _NoOpMetric:
    def labels(self, **kw: Any) -> _NoOpMetric: return self
    def inc(self, *a: Any) -> None: pass
    def observe(self, *a: Any) -> None: pass
    def set(self, *a: Any) -> None: pass
    def dec(self, *a: Any) -> None: pass


# ── 模型定价表（USD per 1K tokens）─────────────────────────────────────────────
# 注意：LLM 厂商定价会频繁调整，建议通过以下方式管理：
#   1. 环境变量：ONION_MODEL_PRICING='{"gpt-4o": [0.005, 0.015]}'
#   2. 配置文件：config.yaml 中的 model_pricing 字段
#   3. 动态加载：从数据库/API 获取最新价格
#   4. 默认值：此处保留作为 fallback
#
# 来源：https://openai.com/api/pricing/ (2024-12)
# 最后更新：2024-12-01
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.005, 0.015),      # prompt, completion
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    # Anthropic
    "claude-3-opus": (0.015, 0.075),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    # 默认值（未知模型）
    "default": (0.01, 0.03),
}


def _load_pricing_from_env() -> dict[str, tuple[float, float]] | None:
    """
    从环境变量加载定价配置（可选）。
    
    环境变量格式：
        ONION_MODEL_PRICING='{"gpt-4o": [0.005, 0.015], "custom-model": [0.01, 0.02]}'
    
    Returns:
        定价字典或 None（如果环境变量未设置）
    """
    import os
    pricing_str = os.getenv("ONION_MODEL_PRICING")
    if not pricing_str:
        return None
    
    try:
        import json
        pricing_dict = json.loads(pricing_str)
        return {k: tuple(v) for k, v in pricing_dict.items()}
    except Exception as exc:
        logger.warning("Failed to parse ONION_MODEL_PRICING: %s", exc)
        return None


# 尝试从环境变量加载定价，fallback 到默认值
_ENV_PRICING = _load_pricing_from_env()
if _ENV_PRICING:
    MODEL_PRICING.update(_ENV_PRICING)
    logger.info("Loaded model pricing from environment variables")


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    custom_pricing: dict[str, tuple[float, float]] | None = None,
) -> float:
    """
    计算 LLM 调用成本（USD）。
    
    Args:
        model: 模型名称
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数
        custom_pricing: 自定义定价表（可选，优先级高于全局 MODEL_PRICING）
    
    Returns:
        成本（美元）
    
    Examples:
        >>> calculate_cost("gpt-4o", 1000, 500)
        0.0125
        
        >>> # 使用自定义定价
        >>> custom = {"my-model": (0.001, 0.002)}
        >>> calculate_cost("my-model", 1000, 500, custom_pricing=custom)
        0.002
    """
    pricing_source = custom_pricing or MODEL_PRICING
    
    # 尝试匹配模型前缀
    pricing = pricing_source.get("default")
    for key, value in pricing_source.items():
        if model.startswith(key):
            pricing = value
            break
    
    if pricing is None:
        return 0.0
    
    prompt_cost = (prompt_tokens / 1000.0) * pricing[0]
    completion_cost = (completion_tokens / 1000.0) * pricing[1]
    return prompt_cost + completion_cost


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

_ACTIVE_REQUESTS: Any = _NoOpMetric()
if _PROM_AVAILABLE:
    from prometheus_client import Gauge as _Gauge
    _ACTIVE_REQUESTS = _Gauge(
        "onion_active_requests",
        "Number of requests currently being processed",
        ["pipeline_name"],
    )

# P95/P99 延迟百分位监控（Summary 指标）
_REQUEST_LATENCY_SUMMARY: Any = _NoOpMetric()
if _PROM_AVAILABLE:
    _REQUEST_LATENCY_SUMMARY = _PromSummary(
        "onion_request_latency_seconds_summary",
        "Pipeline request latency summary (P95/P99)",
        ["pipeline_name", "model"],
    )

# Token 成本追踪
_TOKEN_COST_USD: Any = _NoOpMetric()
if _PROM_AVAILABLE:
    _TOKEN_COST_USD = _PromCounter(
        "onion_token_cost_dollars_total",
        "Total token cost in USD",
        ["pipeline_name", "model", "provider"],
    )


class MetricsMiddleware(BaseMiddleware):
    """
    Prometheus 指标中间件。priority=90（紧跟 TracingMiddleware 之后）。

    所有指标均携带 pipeline_name 标签，便于多 Pipeline 实例区分。

    指标：
      onion_requests_total{pipeline_name, model, finish_reason, status}
      onion_request_duration_seconds{pipeline_name, model} (Histogram)
      onion_request_latency_seconds_summary{pipeline_name, model} (Summary, P95/P99)
      onion_tokens_total{pipeline_name, model, type}
      onion_token_cost_dollars_total{pipeline_name, model, provider}
      onion_tool_calls_total{pipeline_name, tool_name, status}
      onion_active_requests{pipeline_name}
    
    增强功能（v0.9.0）：
      - Summary 指标提供 P95/P99 延迟百分位监控
      - Token 成本追踪（基于模型定价表）
      - 支持通过环境变量 ONION_MODEL_PRICING 动态配置价格
      - 支持运行时传入 custom_pricing 覆盖默认价格
    """

    priority: int = 90

    def __init__(
        self,
        pipeline_name: str = "default",
        custom_pricing: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        """
        Args:
            pipeline_name: Pipeline 名称（用于指标标签）
            custom_pricing: 自定义定价表（可选），优先级高于全局 MODEL_PRICING
        """
        self._pipeline_name = pipeline_name
        self._custom_pricing = custom_pricing

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
        model = response.model or "unknown"
        provider = context.metadata.get("provider_name", "unknown")
        
        self._record_completion(context, model, response.finish_reason or "unknown", "ok")
        
        if response.usage:
            # Token 用量统计
            _TOKEN_USAGE.labels(pipeline_name=self._pipeline_name, model=model, type="prompt").inc(response.usage.prompt_tokens)
            _TOKEN_USAGE.labels(pipeline_name=self._pipeline_name, model=model, type="completion").inc(response.usage.completion_tokens)
            
            # Token 成本追踪
            cost = calculate_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                custom_pricing=self._custom_pricing
            )
            _TOKEN_COST_USD.labels(
                pipeline_name=self._pipeline_name,
                model=model,
                provider=provider
            ).inc(cost)
        
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
            # Histogram 指标（用于平均值和分布）
            _REQUEST_LATENCY.labels(pipeline_name=self._pipeline_name, model=model).observe(duration)
            # Summary 指标（用于 P95/P99 百分位）
            _REQUEST_LATENCY_SUMMARY.labels(pipeline_name=self._pipeline_name, model=model).observe(duration)
        _REQUEST_TOTAL.labels(
            pipeline_name=self._pipeline_name,
            model=model,
            finish_reason=finish_reason,
            status=status,
        ).inc()
