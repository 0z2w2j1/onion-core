"""Onion Core - 上下文窗口管理中间件"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import tiktoken

from ..base import BaseMiddleware
from ..models import (
    AgentContext,
    LLMResponse,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger("onion_core.context")

DEFAULT_MAX_TOKENS = 4000
DEFAULT_KEEP_ROUNDS = 2
DEFAULT_MODEL_ENCODING = "cl100k_base"
DEFAULT_SUMMARY_STRATEGY = "rule-based"
# LRU 缓存最大容量，避免内存泄漏
ENCODING_CACHE_MAX_SIZE = 10


class ContextSummarizer(Protocol):
    async def summarize(self, messages: list[Message]) -> str:
        ...


class RuleBasedContextSummarizer:
    """轻量规则摘要器，优先保留可引用实体信息。"""

    async def summarize(self, messages: list[Message]) -> str:
        if not messages:
            return "No earlier messages to summarize."
        lines: list[str] = []
        for idx, msg in enumerate(messages[-8:], start=1):
            text = " ".join(msg.text_content.split())
            if len(text) > 160:
                text = f"{text[:157]}..."
            lines.append(f"{idx}. ({msg.role}) {text}")
        return "\n".join(lines)


class ContextWindowMiddleware(BaseMiddleware):
    """
    上下文窗口管理中间件。priority=300。

    超出 Token 阈值时执行滑动窗口裁剪，支持通过 context.config 运行时覆盖，
    包括动态指定 encoding 名称（适配不同模型的 tokenizer）。
    
    改进：使用线程池异步执行 tiktoken 计算，避免阻塞事件循环。

    context.config 运行时覆盖示例：
        context.config["context_window"] = {
            "max_tokens": 8000,
            "keep_rounds": 3,
            "encoding_name": "p50k_base",   # 覆盖 encoding
        }
    """

    priority: int = 300
    
    # 线程池用于异步 Token 计算，避免阻塞事件循环
    _executor: ThreadPoolExecutor | None = None

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        keep_rounds: int = DEFAULT_KEEP_ROUNDS,
        encoding_name: str = DEFAULT_MODEL_ENCODING,
        summary_strategy: str = DEFAULT_SUMMARY_STRATEGY,
        summarizer: ContextSummarizer | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._keep_rounds = keep_rounds
        self._default_encoding_name = encoding_name
        self._summary_strategy = summary_strategy
        self._summarizer = summarizer
        self._rule_based_summarizer = RuleBasedContextSummarizer()
        # 默认 encoding（启动时加载）
        self._default_encoding = tiktoken.get_encoding(encoding_name)
        # LRU encoding 缓存，避免重复加载（最大容量 ENCODING_CACHE_MAX_SIZE）
        self._encoding_cache: OrderedDict[str, tiktoken.Encoding] = OrderedDict(
            [(encoding_name, self._default_encoding)]
        )

    def _get_encoding(self, name: str) -> tiktoken.Encoding:
        """按名称获取 encoding，带 LRU 缓存。未知名称回退到默认 encoding 并记录警告。"""
        if name in self._encoding_cache:
            # LRU：移动到末尾（最近使用）
            self._encoding_cache.move_to_end(name)
            return self._encoding_cache[name]
        try:
            enc = tiktoken.get_encoding(name)
            # LRU：添加到缓存，如果超出容量则删除最旧的
            self._encoding_cache[name] = enc
            self._encoding_cache.move_to_end(name)
            if len(self._encoding_cache) > ENCODING_CACHE_MAX_SIZE:
                self._encoding_cache.popitem(last=False)  # 删除最旧的
            logger.debug("Loaded encoding: %s", name)
            return enc
        except Exception as exc:
            logger.warning(
                "Unknown encoding '%s' (%s), falling back to '%s'",
                name, exc, self._default_encoding_name,
            )
            return self._default_encoding

    async def startup(self) -> None:
        # 创建线程池用于异步 Token 计算
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tiktoken")
        logger.info(
            "ContextWindowMiddleware started | max_tokens=%d | keep_rounds=%d | encoding=%s | summary_strategy=%s",
            self._max_tokens,
            self._keep_rounds,
            self._default_encoding_name,
            self._summary_strategy,
        )

    async def shutdown(self) -> None:
        if self._executor:
            self._executor.shutdown(wait=False)
        logger.info("ContextWindowMiddleware stopped.")

    def count_tokens(self, messages: list[Message], encoding: tiktoken.Encoding | None = None) -> int:
        enc = encoding or self._default_encoding
        total = sum(
            4 + len(enc.encode(m.role)) + len(enc.encode(m.text_content))
            + (len(enc.encode(m.name)) if m.name else 0)
            for m in messages
        ) + 2
        return total
    
    async def count_tokens_async(self, messages: list[Message], encoding: tiktoken.Encoding | None = None) -> int:
        """
        异步 Token 计数，使用线程池避免阻塞事件循环。
        
        对于短消息（< 1000 字符），直接使用同步方法以避免线程切换开销。
        对于长消息，使用线程池执行 tiktoken 编码。
        """
        # 快速路径：短消息直接同步计算
        total_chars = sum(len(m.text_content) for m in messages)
        if total_chars < 1000:
            return self.count_tokens(messages, encoding)
        
        # 长消息：使用线程池异步计算
        if not self._executor:
            # fallback：如果线程池未初始化，使用同步方法
            return self.count_tokens(messages, encoding)
        
        loop = asyncio.get_running_loop()
        enc = encoding or self._default_encoding
        
        # 在线程池中执行编码计算
        def _encode_messages() -> int:
            return self.count_tokens(messages, enc)
        
        return await loop.run_in_executor(self._executor, _encode_messages)

    async def _summarize_old_messages(
        self,
        old_messages: list[Message],
        strategy: str,
    ) -> tuple[Message | None, bool]:
        if not old_messages or strategy == "none":
            return None, False

        try:
            if strategy == "rule-based":
                summary_text = await self._rule_based_summarizer.summarize(old_messages)
            elif strategy == "llm-summary":
                if self._summarizer is None:
                    logger.warning("llm-summary requested but no summarizer injected; falling back to rule-based")
                    summary_text = await self._rule_based_summarizer.summarize(old_messages)
                else:
                    summary_text = await self._summarizer.summarize(old_messages)
            else:
                logger.warning("Unknown summary strategy '%s'; disabling summary", strategy)
                return None, False

            summary_msg = Message(
                role=MessageRole.SYSTEM,
                content=f"[Summary: Conversation history truncated]\n{summary_text}",
            )
            return summary_msg, True
        except Exception as exc:
            logger.warning("Summary generation failed, skipping summary: %s", exc)
            return None, False

    async def _truncate_messages(
        self,
        messages: list[Message],
        keep_rounds: int,
        summary_strategy: str,
    ) -> tuple[list[Message], bool]:
        system_msgs = [m for m in messages if m.role == "system"]
        conv_msgs = [m for m in messages if m.role != "system"]
        keep_count = keep_rounds * 2
        if len(conv_msgs) <= keep_count:
            return messages, False
        old_msgs = conv_msgs[:-keep_count]
        kept = conv_msgs[-keep_count:]
        summary_msg, summary_generated = await self._summarize_old_messages(old_msgs, summary_strategy)
        truncated = system_msgs + ([summary_msg] if summary_msg else []) + kept
        logger.info("Context truncated: %d → %d messages (kept last %d rounds)",
                    len(messages), len(truncated), keep_rounds)
        return truncated, summary_generated

    async def process_request(self, context: AgentContext) -> AgentContext:
        rt_cfg = context.config.get("context_window", {})
        max_tokens = rt_cfg.get("max_tokens", self._max_tokens)
        keep_rounds = rt_cfg.get("keep_rounds", self._keep_rounds)
        summary_strategy = rt_cfg.get("summary_strategy", self._summary_strategy)

        # 动态 encoding：优先从 context.config 读取，回退到构造时的默认值
        encoding_name = rt_cfg.get("encoding_name", self._default_encoding_name)
        encoding = self._get_encoding(encoding_name)

        # 使用异步 Token 计数，避免阻塞事件循环
        token_count = await self.count_tokens_async(context.messages, encoding)
        context.metadata["token_count_before"] = token_count
        context.metadata["pre_tokens"] = token_count
        context.metadata["encoding_name"] = encoding_name
        logger.info("[%s] Token count: %d / %d (encoding=%s)",
                    context.request_id, token_count, max_tokens, encoding_name)

        if token_count > max_tokens:
            logger.warning("[%s] Token limit exceeded (%d > %d) — truncating.",
                           context.request_id, token_count, max_tokens)
            context.messages, summary_generated = await self._truncate_messages(
                context.messages,
                keep_rounds,
                summary_strategy,
            )
            post_tokens = self.count_tokens(context.messages, encoding)
            context.metadata["token_count_after"] = post_tokens
            context.metadata["post_tokens"] = post_tokens
            context.metadata["context_truncated"] = True
            context.metadata["truncated"] = True
            context.metadata["summary_generated"] = summary_generated
        else:
            context.metadata["context_truncated"] = False
            context.metadata["truncated"] = False
            context.metadata["summary_generated"] = False
            context.metadata["post_tokens"] = token_count
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
