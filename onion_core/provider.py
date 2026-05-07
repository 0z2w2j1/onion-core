"""
Onion Core - LLM Provider 抽象层
"""

from __future__ import annotations

import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable

from .models import AgentContext, FinishReason, LLMResponse, StreamChunk

logger = logging.getLogger("onion_core.provider")

ResponseLike = LLMResponse | str
CompleteCallable = Callable[[AgentContext], ResponseLike | Awaitable[ResponseLike]]
StreamCallable = Callable[[AgentContext], AsyncIterator[StreamChunk | str]]


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


class CallableProvider(LLMProvider):
    """
    Adapter that wraps an existing LLM callable in the Onion provider interface.

    This is the lowest-friction embedding path for applications that already
    have a working SDK call and only want Onion middleware around it.
    """

    def __init__(
        self,
        complete: CompleteCallable,
        *,
        stream: StreamCallable | None = None,
        model: str = "callable",
        name: str | None = None,
    ) -> None:
        self._complete = complete
        self._stream = stream
        self._model = model
        self._name = name or f"CallableProvider({model})"

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, context: AgentContext) -> LLMResponse:
        result = self._complete(context)
        if inspect.isawaitable(result):
            result = await result
        return self._coerce_response(result)

    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        if self._stream is None:
            response = await self.complete(context)
            text = response.content or ""
            for i, char in enumerate(text):
                yield StreamChunk(
                    delta=char,
                    finish_reason=response.finish_reason if i == len(text) - 1 else None,
                    index=i,
                )
            if not text:
                yield StreamChunk(delta="", finish_reason=response.finish_reason, index=0)
            return

        index = 0
        async for item in self._stream(context):
            if isinstance(item, StreamChunk):
                yield item
            else:
                yield StreamChunk(delta=item, index=index)
            index += 1

    def _coerce_response(self, result: ResponseLike) -> LLMResponse:
        if isinstance(result, LLMResponse):
            if result.model is None:
                return result.model_copy(update={"model": self._model})
            return result
        return LLMResponse(
            content=result,
            finish_reason=FinishReason.STOP,
            model=self._model,
        )
