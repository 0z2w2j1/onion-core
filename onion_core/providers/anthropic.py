"""
Onion Core - Anthropic Provider 适配器

依赖：pip install anthropic>=0.20

用法：
    from onion_core.providers.anthropic import AnthropicProvider
    provider = AnthropicProvider(api_key="sk-ant-...", model="claude-3-5-sonnet-20241022")
    pipeline = Pipeline(provider=provider)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from ..error_codes import ErrorCode
from ..models import AgentContext, LLMResponse, ProviderError, StreamChunk, ToolCall, UsageStats
from ..provider import LLMProvider

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger("onion_core.providers.anthropic")

# Anthropic 的 system 消息需要单独传，不在 messages 列表里
_DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    """
    Anthropic Messages API 适配器。

    支持：
      - 非流式调用（complete）
      - 流式调用（stream）
      - 工具调用（tool_use）
      - system 消息自动提取
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 1.0,
        base_url: str | None = None,
        client: AsyncAnthropic | None = None,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
    ) -> None:
        try:
            import anthropic as _anthropic
        except ImportError as err:
            raise ImportError(
                "anthropic package is required: pip install anthropic>=0.20"
            ) from err

        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            import httpx
            http_client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=max_keepalive_connections,
                )
            )
            client_kwargs: dict[str, Any] = {"api_key": api_key, "http_client": http_client}
            if base_url:
                client_kwargs["base_url"] = base_url
            self._client = _anthropic.AsyncAnthropic(**client_kwargs)

    @property
    def name(self) -> str:
        return f"AnthropicProvider({self._model})"

    def _split_messages(self, context: AgentContext) -> tuple[str, list[dict[str, Any]]]:
        """
        Anthropic API 要求：
        - system 消息单独传
        - tool 结果消息需要包含 tool_use_id，格式为 content block list
        返回 (system_text, messages_list)。
        """
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for msg in context.messages:
            if msg.role == "system":
                # 确保只添加字符串类型的 system 内容
                text = msg.text_content if hasattr(msg, "text_content") else msg.content
                if isinstance(text, str):
                    system_parts.append(text)
            elif msg.role == "tool":
                # Anthropic tool_result 格式：必须包含 tool_use_id
                tool_use_id = msg.name or "unknown"
                content_text = msg.text_content if hasattr(msg, "text_content") else msg.content
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": content_text,
                    }],
                })
            else:
                role = "user" if msg.role == "user" else "assistant"
                content: str | list[dict[str, str]] = ""
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    content = [
                        {"type": b.type, **({"text": b.text} if b.text else {})}
                        for b in msg.content
                    ]
                messages.append({"role": role, "content": content})
        return "\n\n".join(system_parts), messages

    def _build_tools(self, context: AgentContext) -> list[dict[str, Any]] | None:
        """从 context.config 读取工具定义（Anthropic tool_use 格式）。"""
        return context.config.get("tools")

    async def complete(self, context: AgentContext) -> LLMResponse:
        system, messages = self._split_messages(context)
        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=messages,
            temperature=self._temperature,
        )
        if system:
            kwargs["system"] = system
        tools = self._build_tools(context)
        if tools:
            kwargs["tools"] = tools

        try:
            resp = await self._client.messages.create(**kwargs)
        except Exception as exc:
            raise ProviderError(
                f"Anthropic API error: {exc}",
                error_code=ErrorCode.PROVIDER_INVALID_REQUEST,
            ) from exc

        # 拼接所有 text block，而不是只保留最后一个
        text_parts: list[str] = []
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input or {},
                ))

        content_text = "".join(text_parts) if text_parts else None

        # 将 Anthropic 的 stop_reason 映射到 FinishReason 枚举
        from ..models import FinishReason
        finish_reason_map: dict[str, FinishReason] = {
            "end_turn": FinishReason.STOP,
            "max_tokens": FinishReason.LENGTH,
            "stop_sequence": FinishReason.STOP,
            "tool_use": FinishReason.TOOL_CALLS,
            "pause_turn": FinishReason.STOP,
            "refusal": FinishReason.CONTENT_FILTER,
        }
        mapped_reason = finish_reason_map.get(resp.stop_reason) if resp.stop_reason else None

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=mapped_reason,
            usage=UsageStats(
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
                total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            ) if resp.usage else None,
            model=resp.model,
            raw=resp,
        )

    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        system, messages = self._split_messages(context)
        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=messages,
            temperature=self._temperature,
        )
        if system:
            kwargs["system"] = system
        tools = self._build_tools(context)
        if tools:
            kwargs["tools"] = tools

        index = 0
        tool_use_id: str | None = None
        tool_use_name: str | None = None
        tool_input_parts: list[str] = []
        
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    # 处理 ContentBlockStartEvent - 捕获 tool_use 开始
                    if (
                        hasattr(event, 'type') and event.type == 'content_block_start'
                        and hasattr(event, 'content_block') and hasattr(event.content_block, 'type')
                        and event.content_block.type == 'tool_use'
                    ):
                        tool_use_id = getattr(event.content_block, 'id', None)
                        tool_use_name = getattr(event.content_block, 'name', None)
                        tool_input_parts = []
                    
                    # 处理 ContentBlockDeltaEvent - 捕获文本和工具输入增量
                    elif hasattr(event, 'type') and event.type == 'content_block_delta':
                        if hasattr(event, 'delta'):
                            delta = event.delta
                            # 文本增量
                            if hasattr(delta, 'type') and delta.type == 'text_delta':
                                text = getattr(delta, 'text', '')
                                if text:
                                    yield StreamChunk(delta=text, index=index)
                                    index += 1
                            # 工具输入增量
                            elif hasattr(delta, 'type') and delta.type == 'input_json_delta':
                                partial_json = getattr(delta, 'partial_json', '')
                                if partial_json:
                                    tool_input_parts.append(partial_json)
                    
                    # 处理 MessageStopEvent - 产出最终 chunk
                    elif hasattr(event, 'type') and event.type == 'message_stop':
                        final = await stream.get_final_message()
                        from ..models import FinishReason
                        finish_reason_map: dict[str, FinishReason] = {
                            "end_turn": FinishReason.STOP,
                            "max_tokens": FinishReason.LENGTH,
                            "stop_sequence": FinishReason.STOP,
                            "tool_use": FinishReason.TOOL_CALLS,
                            "pause_turn": FinishReason.STOP,
                            "refusal": FinishReason.CONTENT_FILTER,
                        }
                        mapped_reason = finish_reason_map.get(final.stop_reason) if final.stop_reason else None
                        
                        # 如果有工具调用，产出带有 tool_call_delta 的 chunk
                        if tool_use_id and tool_use_name:
                            import json
                            try:
                                tool_arguments = json.loads(''.join(tool_input_parts)) if tool_input_parts else {}
                            except json.JSONDecodeError:
                                tool_arguments = {}
                            
                            yield StreamChunk(
                                delta="",
                                tool_call_delta={
                                    "index": 0,
                                    "id": tool_use_id,
                                    "function_name": tool_use_name,
                                    "arguments": json.dumps(tool_arguments),
                                },
                                finish_reason=mapped_reason,
                                index=index,
                            )
                            index += 1
                        else:
                            yield StreamChunk(
                                delta="",
                                finish_reason=mapped_reason,
                                index=index,
                            )
                            index += 1
        except Exception as exc:
            raise ProviderError(
                f"Anthropic streaming error: {exc}",
                error_code=ErrorCode.PROVIDER_INVALID_REQUEST,
            ) from exc

    async def cleanup(self) -> None:
        """关闭 HTTP 客户端（如果由本实例创建）。"""
        if self._owns_client:
            await self._client.close()

    async def __aenter__(self) -> AnthropicProvider:
        """异步上下文管理器入口。"""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """异步上下文管理器出口，确保资源清理。"""
        await self.cleanup()
