"""
Onion Core - 中间件抽象基类
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from .models import AgentContext, LLMResponse, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger(__name__)


class BaseMiddleware(ABC):
    """
    中间件抽象基类。

    只有 process_request 和 process_response 是抽象方法（必须实现）。
    其余钩子提供透传的默认实现，子类按需覆盖，大幅减少样板代码。

    执行顺序（洋葱模型）：
      request      正序（priority 升序）
      response     逆序
      stream_chunk 逆序
      tool_call    正序
      tool_result  逆序
      error        正序广播

    timeout 属性：
      设置后，该中间件的每次调用使用此超时（秒），覆盖 Pipeline 全局 middleware_timeout。
      None 表示使用全局配置。
    """

    priority: int = 500
    timeout: float | None = None  # 中间件级别超时，覆盖 Pipeline 全局配置
    is_mandatory: bool = False       # 是否为核心中间件。True 时若执行失败（含超时）将直接中断链路并抛出异常。

    @property
    def name(self) -> str:
        return self.__class__.__name__

    # ── 生命周期（默认空操作）────────────────────────────────────────────────

    async def startup(self) -> None:
        """Pipeline 启动时调用，默认空操作。"""
        logger.debug("Middleware %s started.", self.name)

    async def shutdown(self) -> None:
        """Pipeline 关闭时调用，默认空操作。"""
        logger.debug("Middleware %s shutdown.", self.name)

    # ── 必须实现 ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def process_request(self, context: AgentContext) -> AgentContext:
        """请求阶段处理，LLM 调用前执行（正序）。"""
        ...

    @abstractmethod
    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        """响应阶段处理，LLM 返回后执行（逆序）。"""
        ...

    # ── 可选覆盖（默认透传）──────────────────────────────────────────────────

    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk:
        """流式 chunk 处理（逆序），默认透传。"""
        return chunk

    async def on_tool_call(
        self, context: AgentContext, tool_call: ToolCall
    ) -> ToolCall:
        """工具调用拦截（正序），默认透传。"""
        return tool_call

    async def on_tool_result(
        self, context: AgentContext, result: ToolResult
    ) -> ToolResult:
        """工具结果处理（逆序），默认透传。"""
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        """错误广播（正序），默认空操作。"""
        logger.debug("Middleware %s received error: %s", self.name, error)
