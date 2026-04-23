"""
Onion Core - LLM Provider 抽象层
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from .models import AgentContext, LLMResponse, StreamChunk


class LLMProvider(ABC):
    """LLM Provider 抽象基类。实现此接口以接入任意 LLM 服务。"""

    @abstractmethod
    async def complete(self, context: AgentContext) -> LLMResponse:
        """非流式调用，返回完整 LLMResponse。"""
        ...

    @abstractmethod
    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        """流式调用，逐块产出 StreamChunk。"""
        ...

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
            finish_reason="stop",
            model="echo-1.0",
        )

    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        response = await self.complete(context)
        text = response.content or ""
        for i, char in enumerate(text):
            yield StreamChunk(
                delta=char,
                finish_reason="stop" if i == len(text) - 1 else None,
                index=i,
            )
