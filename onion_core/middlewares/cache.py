"""
Onion Core - Response Cache Middleware

提供 LLM 响应缓存功能，避免重复调用相同的请求。
支持 TTL（生存时间）和最大缓存大小限制。

用法：
    from onion_core.middlewares import ResponseCacheMiddleware
    
    pipeline.add_middleware(ResponseCacheMiddleware(ttl_seconds=300, max_size=1000))
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import cast

from ..base import BaseMiddleware
from ..models import AgentContext, FinishReason, LLMResponse, StreamChunk

logger = logging.getLogger("onion_core.middleware.cache")


class ResponseCacheMiddleware(BaseMiddleware):
    """
    响应缓存中间件。
    
    基于请求内容（messages + config）生成缓存键，
    缓存完整的 LLMResponse，在 TTL 内返回缓存结果。
    
    特性：
      - 自动过期（TTL）
      - LRU 淘汰策略
      - 可配置的缓存键生成策略
      - 缓存命中/未命中指标统计
    """

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        max_size: int = 1000,
        cache_key_strategy: str = "full",
    ) -> None:
        """
        Args:
            ttl_seconds: 缓存条目生存时间（秒），默认 5 分钟
            max_size: 最大缓存条目数，默认 1000
            cache_key_strategy: 缓存键生成策略
                - "full": 使用完整 messages + config（默认）
                - "user_only": 仅使用用户消息
                - "custom": 需要子类重写 _generate_cache_key()
        """
        super().__init__()
        # Override class-level attributes
        type(self).priority = 75
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._cache_key_strategy = cache_key_strategy
        
        # LRU 缓存：{cache_key: (timestamp, LLMResponse)}
        self._cache: OrderedDict[str, tuple[float, LLMResponse]] = OrderedDict()
        
        # 统计信息
        self._hits = 0
        self._misses = 0

    @property
    def hits(self) -> int:
        """缓存命中次数。"""
        return self._hits

    @property
    def misses(self) -> int:
        """缓存未命中次数。"""
        return self._misses

    @property
    def hit_rate(self) -> float:
        """缓存命中率（0.0 - 1.0）。"""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def clear_cache(self) -> None:
        """清空所有缓存。"""
        self._cache.clear()
        logger.info("Response cache cleared.")

    def get_cache_size(self) -> int:
        """获取当前缓存条目数。"""
        return len(self._cache)

    async def process_request(self, context: AgentContext) -> AgentContext:
        """
        在请求阶段检查缓存。
        
        如果缓存命中，直接返回缓存的响应（通过抛出特殊异常或设置标志）。
        由于中间件链的设计，我们需要在 response 阶段处理缓存返回。
        这里我们标记上下文，让后续流程知道这是缓存命中。
        """
        cache_key = self._generate_cache_key(context)
        
        # 检查缓存是否存在且未过期
        if cache_key in self._cache:
            timestamp, cached_response = self._cache[cache_key]
            if time.time() - timestamp < self._ttl_seconds:
                # 缓存命中
                self._hits += 1
                
                # 移动到末尾（LRU）
                self._cache.move_to_end(cache_key)
                
                # 在上下文中存储缓存的响应
                context.metadata["_cached_response"] = cached_response
                context.metadata["_cache_hit"] = True
                
                logger.debug(
                    "[%s] Cache HIT (key=%s, ttl=%.1fs remaining)",
                    context.request_id,
                    cache_key[:16],
                    self._ttl_seconds - (time.time() - timestamp),
                )
            else:
                # 缓存过期，删除
                del self._cache[cache_key]
                self._misses += 1
                logger.debug("[%s] Cache EXPIRED (key=%s)", context.request_id, cache_key[:16])
        else:
            self._misses += 1
            logger.debug("[%s] Cache MISS (key=%s)", context.request_id, cache_key[:16])
        
        return context

    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        """
        在响应阶段处理缓存。
        
        如果是缓存命中，直接返回缓存的响应。
        否则，将新响应存入缓存。
        """
        # 检查是否是缓存命中
        if context.metadata.get("_cache_hit"):
            cached_response = context.metadata.pop("_cached_response", None)
            context.metadata.pop("_cache_hit", None)
            
            if cached_response is not None:
                logger.info(
                    "[%s] Returning cached response (hit_rate=%.1f%%)",
                    context.request_id,
                    self.hit_rate * 100,
                )
                # Cast to LLMResponse since we stored it as such
                return cast(LLMResponse, cached_response)
        
        # 缓存新响应（仅当 finish_reason 为 stop 时）
        if response.finish_reason == FinishReason.STOP:
            cache_key = self._generate_cache_key(context)
            self._store_in_cache(cache_key, response)
            logger.debug("[%s] Response cached (key=%s)", context.request_id, cache_key[:16])
        
        return response

    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk:
        """流式响应不缓存（因为需要逐块处理）。"""
        return chunk

    def _generate_cache_key(self, context: AgentContext) -> str:
        """
        生成缓存键。
        
        根据配置的策略生成唯一标识请求的哈希值。
        """
        if self._cache_key_strategy == "user_only":
            # 仅使用用户消息
            user_messages = [
                {"role": m.role, "content": m.content}
                for m in context.messages
                if m.role == "user"
            ]
            key_data: dict[str, object] = {"messages": user_messages}
        else:
            # 默认：使用完整 messages + 相关配置
            messages_for_key = [
                {"role": m.role, "content": str(m.content), "name": str(m.name) if m.name else None}
                for m in context.messages
            ]
            config_for_key = {
                k: v
                for k, v in context.config.items()
                if k in ["temperature", "max_tokens", "top_p"]
            }
            key_data = {"messages": messages_for_key, "config": config_for_key}
        
        # 生成 MD5 哈希
        key_string = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(key_string.encode("utf-8")).hexdigest()

    def _store_in_cache(self, key: str, response: LLMResponse) -> None:
        """
        存储响应到缓存，遵循 LRU 策略。
        """
        # 如果缓存已满，删除最旧的条目
        if len(self._cache) >= self._max_size:
            oldest_key, _ = self._cache.popitem(last=False)
            logger.debug("Cache full, evicted oldest entry (key=%s)", oldest_key[:16])
        
        # 存储新条目
        self._cache[key] = (time.time(), response)
        logger.debug(
            "Cache stored (size=%d/%d, hit_rate=%.1f%%)",
            len(self._cache),
            self._max_size,
            self.hit_rate * 100,
        )

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        """错误时不清除缓存，但记录日志。"""
        logger.warning(
            "[%s] Error occurred, cache stats: hits=%d, misses=%d, hit_rate=%.1f%%",
            context.request_id,
            self._hits,
            self._misses,
            self.hit_rate * 100,
        )
