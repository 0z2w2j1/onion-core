from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, RateLimitExceeded, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.ratelimit")


class RateLimitMiddleware(BaseMiddleware):
    """
    滑动窗口速率限制中间件。priority=150。

    按 session_id 独立计数，LRU 淘汰长期不活跃的 session（防内存泄漏）。
    """

    priority: int = 150
    is_mandatory: bool = True

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: float = 60.0,
        max_sessions: int = 10_000,  # LRU 容量上限
    ) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._max_sessions = max_sessions
        self._windows: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()  # 保护 _windows 的并发访问

    async def startup(self) -> None:
        logger.info("RateLimitMiddleware started | max=%d req / %.0fs | lru_cap=%d",
                    self._max_requests, self._window, self._max_sessions)

    async def shutdown(self) -> None:
        async with self._lock:
            self._windows.clear()
        logger.info("RateLimitMiddleware stopped.")

    def _get_window(self, sid: str) -> deque[float]:
        """获取 session 的时间窗口，LRU 更新访问顺序。调用方必须持有 self._lock。"""
        if sid in self._windows:
            self._windows.move_to_end(sid)
        else:
            if len(self._windows) >= self._max_sessions:
                self._windows.popitem(last=False)  # 淘汰最久未访问的
            self._windows[sid] = deque()
        return self._windows[sid]

    async def process_request(self, context: AgentContext) -> AgentContext:
        sid = context.session_id
        now = time.monotonic()

        async with self._lock:
            window = self._get_window(sid)

            cutoff = now - self._window
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self._max_requests:
                retry_after = self._window - (now - window[0])
                logger.warning("[%s] Rate limit exceeded for session %s (retry after %.1fs)",
                               context.request_id, sid, retry_after)
                raise RateLimitExceeded(
                    f"Rate limit exceeded for session '{sid}'. Retry after {retry_after:.1f}s."
                )

            window.append(now)
            remaining = self._max_requests - len(window)

        context.metadata["rate_limit_remaining"] = remaining
        return context

    async def process_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse:
        return response

    async def process_stream_chunk(self, context: AgentContext, chunk: StreamChunk) -> StreamChunk:
        return chunk

    async def on_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        return tool_call

    async def on_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult:
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        logger.error("[%s] RateLimitMiddleware error: %s", context.request_id, error)

    def get_usage(self, session_id: str) -> dict:
        now = time.monotonic()
        # 注意：此方法为同步，仅做快照读取，不修改结构，竞态影响可接受
        window = self._windows.get(session_id, deque())
        active = sum(1 for t in window if t >= now - self._window)
        return {
            "session_id": session_id,
            "requests_in_window": active,
            "max_requests": self._max_requests,
            "remaining": max(0, self._max_requests - active),
            "window_seconds": self._window,
        }


