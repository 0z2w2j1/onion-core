"""Onion Core - 可观测性中间件"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.observability")

# 线程/协程安全的 trace_id 上下文变量，供日志 Filter 读取
_trace_id_var: ContextVar[str] = ContextVar("sentinel_trace_id", default="")


class TraceIdFilter(logging.Filter):
    """将当前协程的 trace_id 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id_var.get()
        return True


class ObservabilityMiddleware(BaseMiddleware):
    """耗时统计和完整生命周期日志。priority=100 确保最外层包裹。"""

    priority: int = 100

    async def startup(self) -> None:
        logger.info("ObservabilityMiddleware started.")

    async def shutdown(self) -> None:
        logger.info("ObservabilityMiddleware stopped.")

    async def process_request(self, context: AgentContext) -> AgentContext:
        # 将 trace_id 写入 ContextVar，贯穿整个协程调用链
        _trace_id_var.set(context.trace_id)
        context.metadata["start_time"] = time.perf_counter()
        logger.info(
            "[%s] Request started | trace=%s | session=%s | messages=%d",
            context.request_id, context.trace_id, context.session_id, len(context.messages),
        )
        return context

    async def process_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse:
        duration = time.perf_counter() - context.metadata.get("start_time", 0.0)
        context.metadata["duration_s"] = round(duration, 4)
        usage_info = ""
        if response.usage:
            u = response.usage
            usage_info = f" | tokens={u.total_tokens} (prompt={u.prompt_tokens}, completion={u.completion_tokens})"
        logger.info(
            "[%s] Processed in %.4fs | trace=%s | model=%s | finish=%s%s",
            context.request_id, duration, context.trace_id,
            response.model or "unknown", response.finish_reason, usage_info,
        )
        return response

    async def process_stream_chunk(self, context: AgentContext, chunk: StreamChunk) -> StreamChunk:
        if chunk.finish_reason:
            duration = time.perf_counter() - context.metadata.get("start_time", 0.0)
            context.metadata["duration_s"] = round(duration, 4)
            logger.info(
                "[%s] Stream finished in %.4fs | trace=%s | finish=%s",
                context.request_id, duration, context.trace_id, chunk.finish_reason,
            )
        return chunk

    async def on_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        context.metadata.setdefault("tool_calls", []).append(tool_call.name)
        logger.info("[%s] Tool call: %s | args=%s", context.request_id, tool_call.name, tool_call.arguments)
        return tool_call

    async def on_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult:
        logger.info(
            "[%s] Tool result: %s | status=%s",
            context.request_id, result.name, "ERROR" if result.is_error else "OK",
        )
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        duration = time.perf_counter() - context.metadata.get("start_time", 0.0)
        logger.error(
            "[%s] Error after %.4fs | trace=%s — %s: %s",
            context.request_id, duration, context.trace_id, type(error).__name__, error,
            exc_info=True,
        )
