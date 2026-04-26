"""
Onion Core - Distributed Response Cache Middleware (Redis Backend)

提供基于 Redis 的分布式响应缓存功能，支持多实例共享缓存。
使用 JSON 序列化存储 LLMResponse，支持 TTL 和 LRU 淘汰策略。

依赖：pip install redis>=5.0

用法：
    from onion_core.middlewares import DistributedCacheMiddleware
    
    # 基本用法
    cache = DistributedCacheMiddleware(
        redis_url="redis://localhost:6379",
        ttl_seconds=300,
        max_size=1000,
    )
    
    # 自定义配置
    cache = DistributedCacheMiddleware(
        redis_url="redis://localhost:6379/1",  # 使用 database 1
        ttl_seconds=600,
        max_size=5000,
        key_prefix="onion:cache",
        pool_size=20,
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from ..base import BaseMiddleware
from ..models import (
    AgentContext,
    CacheHitException,
    FinishReason,
    LLMResponse,
    StreamChunk,
    UsageStats,
)

logger = logging.getLogger("onion_core.middleware.distributed_cache")


class DistributedCacheMiddleware(BaseMiddleware):
    """
    分布式响应缓存中间件（Redis 后端）。priority=75。
    
    基于请求内容生成缓存键，将 LLMResponse 序列化后存储到 Redis。
    支持多实例共享缓存，避免重复调用相同的 LLM 请求。
    
    特性：
      - 分布式缓存（多实例共享）
      - 自动过期（Redis TTL）
      - LRU 淘汰策略（Redis maxmemory-policy）
      - 可配置的缓存键生成策略
      - 缓存命中/未命中指标统计
      - 流式响应不支持（需逐块处理）
    
    注意：
      - 需要在 Redis 配置中设置 maxmemory-policy allkeys-lru
      - 建议为缓存单独使用一个 Redis database
      - 流式响应不缓存，仅缓存完整响应
    """

    priority: int = 75

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        ttl_seconds: float = 300.0,
        max_size: int = 1000,
        key_prefix: str = "onion:cache",
        pool_size: int = 10,
        cache_key_strategy: str = "full",
    ) -> None:
        """
        Args:
            redis_url: Redis 连接 URL
            ttl_seconds: 缓存条目生存时间（秒），默认 5 分钟
            max_size: 最大缓存条目数（通过 Redis maxmemory 控制）
            key_prefix: Redis key 前缀
            pool_size: Redis 连接池大小
            cache_key_strategy: 缓存键生成策略
                - "full": 使用完整 messages + config（默认）
                - "user_only": 仅使用用户消息
                - "custom": 需要子类重写 _generate_cache_key()
        """
        try:
            import redis.asyncio as redis
        except ImportError as err:
            raise ImportError(
                "redis package is required: pip install redis>=5.0"
            ) from err

        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._key_prefix = key_prefix
        self._cache_key_strategy = cache_key_strategy
        
        # 统计信息（使用锁保护并发访问）
        self._hits = 0
        self._misses = 0
        self._stats_lock = asyncio.Lock()
        
        # Redis 连接
        self._redis_pool = redis.ConnectionPool.from_url(
            redis_url,
            max_connections=pool_size,
            decode_responses=True,
            socket_connect_timeout=5.0,  # 防止启动时 hang
            socket_timeout=5.0,  # 防止操作时 hang
        )
        self._redis: redis.Redis | None = None

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

    async def startup(self) -> None:
        """初始化 Redis 连接。"""
        import redis.asyncio as redis
        
        self._redis = redis.Redis(connection_pool=self._redis_pool)
        
        try:
            # 测试连接（redis.asyncio 的 ping() 始终是 coroutine）
            await self._redis.ping()  # type: ignore[misc]
            logger.info(
                "DistributedCacheMiddleware started | redis=%s | ttl=%.0fs | strategy=%s",
                self._redis_url, self._ttl_seconds, self._cache_key_strategy
            )
        except Exception as exc:
            logger.error("Failed to connect to Redis: %s", exc)
            raise

    async def shutdown(self) -> None:
        """关闭 Redis 连接。"""
        if self._redis:
            await self._redis.aclose()
            logger.info(
                "DistributedCacheMiddleware stopped | hits=%d | misses=%d | hit_rate=%.1f%%",
                self._hits, self._misses, self.hit_rate * 100
            )

    async def clear_cache(self) -> None:
        """清空所有缓存。"""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        pattern = f"{self._key_prefix}:*"
        cursor = 0
        deleted = 0
        
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self._redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        
        logger.info("Distributed cache cleared (deleted %d keys)", deleted)

    async def get_cache_size(self) -> int:
        """获取当前缓存条目数。"""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        pattern = f"{self._key_prefix}:*"
        count = 0
        cursor = 0
        
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            count += len(keys)
            if cursor == 0:
                break
        
        return count

    async def process_request(self, context: AgentContext) -> AgentContext:
        """
        在请求阶段检查缓存。
        
        如果缓存命中，抛出 CacheHitException 中断 Provider 调用，
        Pipeline 捕获后直接返回缓存的响应，行为与 ResponseCacheMiddleware 一致。
        """
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        cache_key = self._generate_cache_key(context)
        redis_key = f"{self._key_prefix}:{cache_key}"

        try:
            cached_data = await self._redis.get(redis_key)

            if cached_data:
                cached_response = self._deserialize_response(cached_data)
                async with self._stats_lock:
                    self._hits += 1

                logger.info(
                    "[%s] Cache HIT (key=%s, ttl=%.0fs, hit_rate=%.1f%%)",
                    context.request_id,
                    cache_key[:16],
                    self._ttl_seconds,
                    self.hit_rate * 100,
                )

                raise CacheHitException(cached_response)
            else:
                async with self._stats_lock:
                    self._misses += 1
                logger.debug("[%s] Cache MISS (key=%s)", context.request_id, cache_key[:16])

        except CacheHitException:
            raise
        except Exception as exc:
            logger.error("[%s] Redis cache error: %s", context.request_id, exc)
            async with self._stats_lock:
                self._misses += 1

        return context

    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        """
        在响应阶段缓存新响应。
        """
        if response.finish_reason == FinishReason.STOP:
            cache_key = self._generate_cache_key(context)
            await self._store_in_cache(cache_key, response)
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
                {"role": m.role, "content": str(m.content)}
                for m in context.messages
                if m.role == "user"
            ]
            key_data: dict[str, object] = {"messages": user_messages}
        else:
            # 默认：使用完整 messages + 相关配置
            messages_for_key = [
                {
                    "role": m.role,
                    "content": str(m.content),
                    "name": str(m.name) if m.name else None,
                }
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

    async def _store_in_cache(self, key: str, response: LLMResponse) -> None:
        """
        存储响应到 Redis 缓存。
        """
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        redis_key = f"{self._key_prefix}:{key}"
        
        try:
            # 序列化响应
            serialized = self._serialize_response(response)
            
            # 存储到 Redis，设置 TTL
            await self._redis.setex(
                redis_key,
                int(self._ttl_seconds),
                serialized,
            )
            
            logger.debug(
                "Cache stored (ttl=%.0fs, hit_rate=%.1f%%)",
                self._ttl_seconds,
                self.hit_rate * 100,
            )
        except Exception as exc:
            logger.error("Failed to store cache: %s", exc)

    def _serialize_response(self, response: LLMResponse) -> str:
        """序列化 LLMResponse 为 JSON 字符串。"""
        data = {
            "content": response.content,
            "tool_calls": [tc.model_dump() for tc in response.tool_calls],
            "finish_reason": response.finish_reason.value if response.finish_reason else None,
            "usage": response.usage.model_dump() if response.usage else None,
            "model": response.model,
        }
        return json.dumps(data, ensure_ascii=False, default=str)

    def _deserialize_response(self, data: str) -> LLMResponse:
        """从 JSON 字符串反序列化为 LLMResponse。"""
        obj = json.loads(data)
        
        from ..models import ToolCall
        
        tool_calls = [
            ToolCall(**tc) for tc in obj.get("tool_calls", [])
        ]
        
        usage = None
        if obj.get("usage"):
            usage = UsageStats(**obj["usage"])
        
        finish_reason = None
        if obj.get("finish_reason"):
            finish_reason = FinishReason(obj["finish_reason"])
        
        return LLMResponse(
            content=obj.get("content"),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=obj.get("model"),
        )

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        """错误时记录日志。"""
        logger.warning(
            "[%s] Error occurred, cache stats: hits=%d, misses=%d, hit_rate=%.1f%%",
            context.request_id,
            self._hits,
            self._misses,
            self.hit_rate * 100,
        )
