"""
Onion Core - Distributed Rate Limit Middleware (Redis Backend)

提供基于 Redis 的分布式限流功能，支持多实例部署。
使用 Redis + Lua 脚本实现原子性的滑动窗口算法。

依赖：pip install redis>=5.0

用法：
    from onion_core.middlewares import DistributedRateLimitMiddleware
    
    # 基本用法
    middleware = DistributedRateLimitMiddleware(
        redis_url="redis://localhost:6379",
        max_requests=60,
        window_seconds=60.0,
    )
    
    # 带连接池配置
    middleware = DistributedRateLimitMiddleware(
        redis_url="redis://localhost:6379",
        max_requests=100,
        window_seconds=60.0,
        pool_size=10,
        key_prefix="onion:ratelimit",
    )
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..base import BaseMiddleware
from ..models import AgentContext, LLMResponse, RateLimitExceeded, StreamChunk, ToolCall, ToolResult

logger = logging.getLogger("onion_core.middleware.distributed_ratelimit")

# Lua 脚本：原子性执行滑动窗口限流
# KEYS[1]: rate limit key (e.g., "onion:ratelimit:{session_id}")
# ARGV[1]: current timestamp
# ARGV[2]: window size in seconds
# ARGV[3]: max requests allowed
# Returns: [remaining_requests, retry_after (0 if allowed)]
LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])

-- Remove expired entries
local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)

-- Count current requests in window
local current_count = redis.call('ZCARD', key)

if current_count >= max_requests then
    -- Rate limit exceeded
    -- Get the oldest entry to calculate retry_after
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if #oldest > 0 then
        retry_after = window - (now - tonumber(oldest[2]))
        if retry_after < 0 then
            retry_after = 0
        end
    end
    return {0, math.ceil(retry_after * 1000) / 1000}
else
    -- Add current request
    redis.call('ZADD', key, now, now .. ':' .. math.random(1000000))
    -- Set expiry to auto-cleanup
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    
    local remaining = max_requests - current_count - 1
    return {remaining, 0}
end
"""


class DistributedRateLimitMiddleware(BaseMiddleware):
    """
    分布式速率限制中间件（Redis 后端）。priority=150。
    
    使用 Redis Sorted Set 实现滑动窗口算法，支持多实例共享限流状态。
    通过 Lua 脚本保证原子性操作，避免竞态条件。
    
    特性：
      - 分布式限流（多实例共享状态）
      - 原子性操作（Lua 脚本）
      - 自动过期清理（Redis TTL）
      - 连接池管理
      - 降级策略（Redis 不可用时可选跳过或拒绝）
    """

    priority: int = 150
    is_mandatory: bool = True

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_requests: int = 60,
        window_seconds: float = 60.0,
        key_prefix: str = "onion:ratelimit",
        pool_size: int = 10,
        fallback_allow: bool = False,  # Redis 不可用时是否允许请求
    ) -> None:
        """
        Args:
            redis_url: Redis 连接 URL
            max_requests: 时间窗口内最大请求数
            window_seconds: 时间窗口大小（秒）
            key_prefix: Redis key 前缀
            pool_size: Redis 连接池大小
            fallback_allow: Redis 不可用时是否允许请求（True=允许，False=拒绝）
        """
        try:
            import redis.asyncio as redis
        except ImportError as err:
            raise ImportError(
                "redis package is required: pip install redis>=5.0"
            ) from err

        self._redis_url = redis_url
        self._max_requests = max_requests
        self._window = window_seconds
        self._key_prefix = key_prefix
        self._fallback_allow = fallback_allow
        self._lua_script_sha: str | None = None

        # 创建 Redis 连接池
        self._redis_pool = redis.ConnectionPool.from_url(
            redis_url,
            max_connections=pool_size,
            decode_responses=True,
        )
        self._redis: redis.Redis | None = None

    async def startup(self) -> None:
        """初始化 Redis 连接并加载 Lua 脚本。"""
        import redis.asyncio as redis
        
        self._redis = redis.Redis(connection_pool=self._redis_pool)
        
        try:
            # 测试连接
            await self._redis.ping()
            
            # 注册 Lua 脚本
            self._lua_script_sha = await self._redis.script_load(LUA_SLIDING_WINDOW)
            
            logger.info(
                "DistributedRateLimitMiddleware started | redis=%s | max=%d req / %.0fs | fallback=%s",
                self._redis_url, self._max_requests, self._window, 
                "allow" if self._fallback_allow else "deny"
            )
        except Exception as exc:
            logger.error("Failed to connect to Redis: %s", exc)
            if not self._fallback_allow:
                raise

    async def shutdown(self) -> None:
        """关闭 Redis 连接。"""
        if self._redis:
            await self._redis.aclose()
            logger.info("DistributedRateLimitMiddleware stopped.")

    async def process_request(self, context: AgentContext) -> AgentContext:
        """检查限流状态。"""
        sid = context.session_id
        key = f"{self._key_prefix}:{sid}"
        now = time.time()

        try:
            if not self._redis or not self._lua_script_sha:
                raise RuntimeError("Redis not initialized")

            # 执行 Lua 脚本
            result = await self._redis.evalsha(
                self._lua_script_sha,
                1,  # number of keys
                key,
                str(now),
                str(self._window),
                str(self._max_requests),
            )

            remaining = int(result[0])
            retry_after = float(result[1])

            if remaining < 0:
                # 限流触发
                logger.warning(
                    "[%s] Rate limit exceeded for session %s (retry after %.1fs)",
                    context.request_id, sid, retry_after
                )
                raise RateLimitExceeded(
                    f"Rate limit exceeded for session '{sid}'. Retry after {retry_after:.1f}s."
                )

            # 记录剩余配额
            context.metadata["rate_limit_remaining"] = remaining
            logger.debug(
                "[%s] Rate limit check passed for session %s (remaining=%d)",
                context.request_id, sid, remaining
            )

        except RateLimitExceeded:
            raise
        except Exception as exc:
            logger.error("[%s] Redis error: %s", context.request_id, exc)
            if self._fallback_allow:
                logger.warning("[%s] Allowing request due to Redis failure", context.request_id)
                context.metadata["rate_limit_remaining"] = -1  # Unknown
            else:
                raise RateLimitExceeded(
                    f"Rate limiter unavailable: {exc}"
                ) from exc

        return context

    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        return response

    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk:
        return chunk

    async def on_tool_call(
        self, context: AgentContext, tool_call: ToolCall
    ) -> ToolCall:
        return tool_call

    async def on_tool_result(
        self, context: AgentContext, result: ToolResult
    ) -> ToolResult:
        return result

    async def on_error(self, context: AgentContext, error: Exception) -> None:
        logger.error("[%s] DistributedRateLimitMiddleware error: %s", context.request_id, error)

    async def get_usage(self, session_id: str) -> dict[str, Any]:
        """
        获取 session 的限流使用情况。
        
        Returns:
            包含限流状态的字典
        """
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        key = f"{self._key_prefix}:{session_id}"
        now = time.time()
        cutoff = now - self._window

        try:
            # 清理过期条目
            await self._redis.zremrangebyscore(key, "-inf", cutoff)
            
            # 获取当前计数
            current_count = await self._redis.zcard(key)
            
            return {
                "session_id": session_id,
                "requests_in_window": current_count,
                "max_requests": self._max_requests,
                "remaining": max(0, self._max_requests - current_count),
                "window_seconds": self._window,
                "distributed": True,
            }
        except Exception as exc:
            logger.error("Failed to get usage for session %s: %s", session_id, exc)
            return {
                "session_id": session_id,
                "error": str(exc),
                "distributed": True,
            }

    async def reset_session(self, session_id: str) -> None:
        """重置指定 session 的限流计数。"""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        key = f"{self._key_prefix}:{session_id}"
        await self._redis.delete(key)
        logger.info("Rate limit reset for session %s", session_id)

    async def reset_all(self) -> None:
        """重置所有限流计数（谨慎使用）。"""
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
        
        logger.info("All rate limits reset (deleted %d keys)", deleted)
