"""Onion Core - 上下文窗口管理中间件"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import tiktoken

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, Message, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.context")

DEFAULT_MAX_TOKENS = 4000
DEFAULT_KEEP_ROUNDS = 2
DEFAULT_MODEL_ENCODING = "cl100k_base"


class ContextWindowMiddleware(BaseMiddleware):
    """
    上下文窗口管理中间件。priority=300。

    超出 Token 阈值时执行滑动窗口裁剪，支持通过 context.config 运行时覆盖，
    包括动态指定 encoding 名称（适配不同模型的 tokenizer）。

    context.config 运行时覆盖示例：
        context.config["context_window"] = {
            "max_tokens": 8000,
            "keep_rounds": 3,
            "encoding_name": "p50k_base",   # 覆盖 encoding
        }
    """

    priority: int = 300

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        keep_rounds: int = DEFAULT_KEEP_ROUNDS,
        encoding_name: str = DEFAULT_MODEL_ENCODING,
    ) -> None:
        self._max_tokens = max_tokens
        self._keep_rounds = keep_rounds
        self._default_encoding_name = encoding_name
        # 默认 encoding（启动时加载）
        self._default_encoding = tiktoken.get_encoding(encoding_name)
        # encoding 缓存，避免重复加载
        self._encoding_cache: Dict[str, tiktoken.Encoding] = {
            encoding_name: self._default_encoding
        }

    def _get_encoding(self, name: str) -> tiktoken.Encoding:
        """按名称获取 encoding，带缓存。未知名称回退到默认 encoding 并记录警告。"""
        if name in self._encoding_cache:
            return self._encoding_cache[name]
        try:
            enc = tiktoken.get_encoding(name)
            self._encoding_cache[name] = enc
            logger.debug("Loaded encoding: %s", name)
            return enc
        except Exception as exc:
            logger.warning(
                "Unknown encoding '%s' (%s), falling back to '%s'",
                name, exc, self._default_encoding_name,
            )
            return self._default_encoding

    async def startup(self) -> None:
        logger.info("ContextWindowMiddleware started | max_tokens=%d | keep_rounds=%d | encoding=%s",
                    self._max_tokens, self._keep_rounds, self._default_encoding_name)

    async def shutdown(self) -> None:
        logger.info("ContextWindowMiddleware stopped.")

    def count_tokens(self, messages: List[Message], encoding: Optional[tiktoken.Encoding] = None) -> int:
        enc = encoding or self._default_encoding
        total = sum(
            4 + len(enc.encode(m.role)) + len(enc.encode(m.text_content))
            + (len(enc.encode(m.name)) if m.name else 0)
            for m in messages
        ) + 2
        return total

    def _truncate_messages(self, messages: List[Message], keep_rounds: int) -> List[Message]:
        system_msgs = [m for m in messages if m.role == "system"]
        conv_msgs = [m for m in messages if m.role != "system"]
        keep_count = keep_rounds * 2
        if len(conv_msgs) <= keep_count:
            return messages
        kept = conv_msgs[-keep_count:]
        summary = Message(role="system", content="[Summary: Conversation history truncated due to token limit]")
        truncated = system_msgs + [summary] + kept
        logger.info("Context truncated: %d → %d messages (kept last %d rounds)",
                    len(messages), len(truncated), keep_rounds)
        return truncated

    async def process_request(self, context: AgentContext) -> AgentContext:
        rt_cfg = context.config.get("context_window", {})
        max_tokens = rt_cfg.get("max_tokens", self._max_tokens)
        keep_rounds = rt_cfg.get("keep_rounds", self._keep_rounds)

        # 动态 encoding：优先从 context.config 读取，回退到构造时的默认值
        encoding_name = rt_cfg.get("encoding_name", self._default_encoding_name)
        encoding = self._get_encoding(encoding_name)

        token_count = self.count_tokens(context.messages, encoding)
        context.metadata["token_count_before"] = token_count
        context.metadata["encoding_name"] = encoding_name
        logger.info("[%s] Token count: %d / %d (encoding=%s)",
                    context.request_id, token_count, max_tokens, encoding_name)

        if token_count > max_tokens:
            logger.warning("[%s] Token limit exceeded (%d > %d) — truncating.",
                           context.request_id, token_count, max_tokens)
            context.messages = self._truncate_messages(context.messages, keep_rounds)
            context.metadata["token_count_after"] = self.count_tokens(context.messages, encoding)
            context.metadata["context_truncated"] = True
        else:
            context.metadata["context_truncated"] = False
        return context

    async def process_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse:
        if response.usage:
            context.metadata["usage"] = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return response

    async def process_stream_chunk(self, context: AgentContext, chunk: StreamChunk) -> StreamChunk:
        return chunk

    async def on_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        return tool_call

    async def on_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult:
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        logger.error("[%s] Context middleware error: %s", context.request_id, error)
