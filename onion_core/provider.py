"""
Onion Core - LLM Provider 抽象层
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .models import AgentContext, FinishReason, LLMResponse, StreamChunk

logger = logging.getLogger("onion_core.provider")


class LLMProvider(ABC):
    """LLM Provider 抽象基类。实现此接口以接入任意 LLM 服务。"""

    @abstractmethod
    async def complete(self, context: AgentContext) -> LLMResponse:
        """非流式调用，返回完整 LLMResponse。"""
        ...

    @abstractmethod
    def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        """流式调用，逐块产出 StreamChunk。"""

    async def cleanup(self) -> None:
        """释放 Provider 占用的资源（HTTP 连接等）。Pipeline shutdown 时自动调用。"""
        logger.debug("Provider '%s' cleanup skipped (no resources).", self.name)

    @property
    def name(self) -> str:
        return self.__class__.__name__


class EchoProvider(LLMProvider):
    """内置 Echo Provider，用于测试和演示，不调用任何外部服务。"""

    def __init__(self, reply: str = "Hello, I am an agent.") -> None:
        self._reply = reply

    async def complete(self, context: AgentContext) -> LLMResponse:
        last_user = next(
            (m.content for m in reversed(context.messages) if m.role == "user"), ""
        )
        reply = self._reply if self._reply is not None else f"Echo: {last_user}"
        return LLMResponse(
            content=reply,
            finish_reason=FinishReason.STOP,
            model="echo-1.0",
        )

    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        response = await self.complete(context)
        text = response.content or ""
        for i, char in enumerate(text):
            yield StreamChunk(
                delta=char,
                finish_reason=FinishReason.STOP if i == len(text) - 1 else None,
                index=i,
            )
