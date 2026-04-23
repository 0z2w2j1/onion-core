"""
Onion Core - OpenAI Provider 适配器

依赖：pip install openai>=1.0

用法：
    from onion_core.providers.openai import OpenAIProvider
    provider = OpenAIProvider(api_key="sk-...", model="gpt-4o")
    pipeline = Pipeline(provider=provider)
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ..models import AgentContext, LLMResponse, ProviderError, StreamChunk, ToolCall, UsageStats
from ..provider import LLMProvider

logger = logging.getLogger("onion_core.providers.openai")


class OpenAIProvider(LLMProvider):
    """
    OpenAI Chat Completions API 适配器。

    支持：
      - 非流式调用（complete）
      - 流式调用（stream）
      - 工具调用（tool_calls）
      - 自定义 base_url（兼容 Azure OpenAI / 本地代理）
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        organization: str | None = None,
        default_headers: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as err:
            raise ImportError(
                "openai package is required: pip install openai>=1.0"
            ) from err

        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            default_headers=default_headers or {},
        )

    @property
    def name(self) -> str:
        return f"OpenAIProvider({self._model})"

    def _build_messages(self, context: AgentContext) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in m.model_dump().items() if v is not None}
            for m in context.messages
        ]

    def _build_tools(self, context: AgentContext) -> list[dict[str, Any]] | None:
        """从 context.config 读取工具定义（OpenAI function calling 格式）。"""
        tools = context.config.get("tools")
        return tools if tools else None

    async def complete(self, context: AgentContext) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=self._build_messages(context),
            temperature=self._temperature,
        )
        if self._max_tokens:
            kwargs["max_tokens"] = self._max_tokens
        tools = self._build_tools(context)
        if tools:
            kwargs["tools"] = tools

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise ProviderError(f"OpenAI API error: {exc}") from exc

        choice = resp.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCall(
                    id=str(tc.id),
                    name=str(tc.function.name),
                    arguments=args,
                ))

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=UsageStats(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            ) if resp.usage else None,
            model=resp.model,
            raw=resp,
        )

    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=self._build_messages(context),
            temperature=self._temperature,
            stream=True,
        )
        if self._max_tokens:
            kwargs["max_tokens"] = self._max_tokens

        try:
            # 使用 stream=True 的 create()，返回可异步迭代的流对象
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise ProviderError(f"OpenAI API error: {exc}") from exc

        index = 0
        try:
            async for chunk in response:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta
                yield StreamChunk(
                    delta=delta.content or "",
                    finish_reason=choice.finish_reason,
                    index=index,
                )
                index += 1
        except Exception as exc:
            raise ProviderError(f"OpenAI streaming error: {exc}") from exc
