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
from ..error_codes import ErrorCode
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
      - 分层限流：区分普通请求和工具调用
      - 原子性操作（Lua 脚本）
      - 自动过期清理（Redis TTL）
      - 连接池管理
      - 降级策略（Redis 不可用时可选跳过或拒绝）
    
    改进（v0.9.0）：
      - 支持 max_tool_calls 和 tool_call_window 参数
      - 自动检测工具调用结果并应用独立限流策略
      - 防止工具调用风暴耗尽普通对话配额
    """

    priority: int = 150
    is_mandatory: bool = True

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_requests: int = 60,
        window_seconds: float = 60.0,
        max_tool_calls: int | None = None,  # 新增：工具调用独立限额
        tool_call_window: float | None = None,  # 新增：工具调用独立窗口
        key_prefix: str = "onion:ratelimit",
        pool_size: int = 10,
        fallback_allow: bool = False,  # Redis 不可用时是否允许请求
    ) -> None:
        """
        Args:
            redis_url: Redis 连接 URL
            max_requests: 时间窗口内最大普通请求数
            window_seconds: 普通请求时间窗口大小（秒）
            max_tool_calls: 工具调用独立限额（默认与 max_requests 相同）
            tool_call_window: 工具调用独立窗口（默认与 window_seconds 相同）
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
        self._max_tool_calls = max_tool_calls or max_requests
        self._tool_call_window = tool_call_window or window_seconds
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
            ping_result = self._redis.ping()
            if not isinstance(ping_result, bool):
                await ping_result
            
            # 注册 Lua 脚本
            script_result = self._redis.script_load(LUA_SLIDING_WINDOW)
            if isinstance(script_result, str):
                self._lua_script_sha = script_result
            else:
                self._lua_script_sha = await script_result
            
            logger.info(
                "DistributedRateLimitMiddleware started | redis=%s | requests=%d/%.0fs | tool_calls=%d/%.0fs | fallback=%s",
                self._redis_url, self._max_requests, self._window,
                self._max_tool_calls, self._tool_call_window,
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
        """检查限流状态，支持分层限流。"""
        sid = context.session_id
        now = time.time()
        
        # 检测是否为工具调用结果阶段（检查最近的消息中是否有 tool 角色）
        is_tool_result = any(m.role == "tool" for m in context.messages[-3:])
        
        # 根据请求类型选择对应的限流配置
        if is_tool_result:
            max_req = self._max_tool_calls
            win_sec = self._tool_call_window
            limit_type = "tool_call"
            key_suffix = "tool"
        else:
            max_req = self._max_requests
            win_sec = self._window
            limit_type = "request"
            key_suffix = "req"
        
        key = f"{self._key_prefix}:{sid}:{key_suffix}"

        try:
            if not self._redis or not self._lua_script_sha:
                raise RuntimeError("Redis not initialized")

            # 执行 Lua 脚本
            evalsha_result = self._redis.evalsha(
                self._lua_script_sha,
                1,  # number of keys
                key,
                str(now),
                str(win_sec),
                str(max_req),
            )
            # redis.asyncio 版本兼容性：某些版本返回 Awaitable，某些直接返回值
            if isinstance(evalsha_result, (list, tuple)):
                result = evalsha_result
            else:
                result = await evalsha_result  # type: ignore[misc]

            remaining = int(result[0])
            retry_after = float(result[1])

            if remaining < 0:
                # 限流触发
                logger.warning(
                    "[%s] %s rate limit exceeded for session %s (retry after %.1fs)",
                    context.request_id, limit_type, sid, retry_after
                )
                raise RateLimitExceeded(
                    f"Rate limit exceeded ({limit_type}) for session '{sid}'. "
                    f"Retry after {retry_after:.1f}s.",
                    error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
                )

            # 记录剩余配额和限流类型
            context.metadata["rate_limit_remaining"] = remaining
            context.metadata["rate_limit_type"] = limit_type
            logger.debug(
                "[%s] %s rate limit check passed for session %s (remaining=%d)",
                context.request_id, limit_type, sid, remaining
            )

        except RateLimitExceeded:
            raise
        except Exception as exc:
            logger.error("[%s] Redis error: %s", context.request_id, exc)
            if self._fallback_allow:
                logger.warning("[%s] Allowing request due to Redis failure", context.request_id)
                context.metadata["rate_limit_remaining"] = -1  # Unknown
                context.metadata["rate_limit_type"] = limit_type
            else:
                raise RateLimitExceeded(
                    f"Rate limiter unavailable: {exc}",
                    error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
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
        获取 session 的限流使用情况（分层统计）。
        
        Returns:
            包含限流状态的字典，包括普通请求和工具调用的独立统计
        """
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        now = time.time()
        
        try:
            # 获取普通请求统计
            req_key = f"{self._key_prefix}:{session_id}:req"
            await self._redis.zremrangebyscore(req_key, "-inf", now - self._window)
            req_count = await self._redis.zcard(req_key)
            
            # 获取工具调用统计
            tool_key = f"{self._key_prefix}:{session_id}:tool"
            await self._redis.zremrangebyscore(tool_key, "-inf", now - self._tool_call_window)
            tool_count = await self._redis.zcard(tool_key)
            
            return {
                "session_id": session_id,
                "requests_in_window": req_count,
                "max_requests": self._max_requests,
                "request_remaining": max(0, self._max_requests - req_count),
                "tool_calls_in_window": tool_count,
                "max_tool_calls": self._max_tool_calls,
                "tool_call_remaining": max(0, self._max_tool_calls - tool_count),
                "window_seconds": self._window,
                "tool_call_window_seconds": self._tool_call_window,
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
        """重置指定 session 的所有限流计数（普通请求 + 工具调用）。"""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        req_key = f"{self._key_prefix}:{session_id}:req"
        tool_key = f"{self._key_prefix}:{session_id}:tool"
        await self._redis.delete(req_key, tool_key)
        logger.info("Rate limit reset for session %s (both request and tool_call)", session_id)

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
        
        logger.info("All distributed rate limits reset (deleted %d keys)", deleted)
