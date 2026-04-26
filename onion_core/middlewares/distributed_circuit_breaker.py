"""
Onion Core - Distributed Circuit Breaker Middleware (Redis Backend)

提供基于 Redis 的分布式熔断器功能，支持多实例共享熔断状态。
使用 Redis Hash 存储熔断器状态，通过 Lua 脚本保证原子性操作。

依赖：pip install redis>=5.0

用法：
    from onion_core.middlewares import DistributedCircuitBreakerMiddleware
    
    # 基本用法
    cb = DistributedCircuitBreakerMiddleware(
        redis_url="redis://localhost:6379",
        failure_threshold=5,
        recovery_timeout=30.0,
        success_threshold=2,
    )
    
    # 监控多个 Provider
    cb.add_provider("openai-gpt4")
    cb.add_provider("anthropic-claude")
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..base import BaseMiddleware
from ..models import (
    AgentContext,
    CircuitBreakerError,
    LLMResponse,
    StreamChunk,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger("onion_core.middleware.distributed_circuit_breaker")

# Lua 脚本：原子性更新熔断器状态
# KEYS[1]: circuit breaker key (e.g., "onion:cb:{provider_name}")
# ARGV[1]: action ("success" or "failure")
# ARGV[2]: current timestamp
# ARGV[3]: failure_threshold
# ARGV[4]: recovery_timeout
# ARGV[5]: success_threshold
# Returns: [new_state, failure_count, success_count]
LUA_UPDATE_STATE = """
local key = KEYS[1]
local action = ARGV[1]
local now = tonumber(ARGV[2])
local failure_threshold = tonumber(ARGV[3])
local recovery_timeout = tonumber(ARGV[4])
local success_threshold = tonumber(ARGV[5])

-- Get current state
local state = redis.call('HGET', key, 'state') or 'CLOSED'
local failure_count = tonumber(redis.call('HGET', key, 'failure_count')) or 0
local success_count = tonumber(redis.call('HGET', key, 'success_count')) or 0
local last_failure_time = tonumber(redis.call('HGET', key, 'last_failure_time')) or 0

if action == 'failure' then
    -- Record failure
    redis.call('HSET', key, 'last_failure_time', now)
    
    if state == 'CLOSED' then
        failure_count = failure_count + 1
        redis.call('HSET', key, 'failure_count', failure_count)
        
        if failure_count >= failure_threshold then
            state = 'OPEN'
            redis.call('HSET', key, 'state', 'OPEN')
        end
    elseif state == 'HALF_OPEN' then
        -- Any failure in HALF_OPEN returns to OPEN
        state = 'OPEN'
        redis.call('HSET', key, 'state', 'OPEN')
        failure_count = failure_count + 1
        redis.call('HSET', key, 'failure_count', failure_count)
    end
    
elseif action == 'success' then
    -- Record success
    if state == 'HALF_OPEN' then
        success_count = success_count + 1
        redis.call('HSET', key, 'success_count', success_count)
        
        if success_count >= success_threshold then
            -- Recovered: reset to CLOSED
            state = 'CLOSED'
            failure_count = 0
            success_count = 0
            redis.call('HSET', key, 'state', 'CLOSED')
            redis.call('HSET', key, 'failure_count', 0)
            redis.call('HSET', key, 'success_count', 0)
        end
    elseif state == 'CLOSED' then
        -- Reset failure count on success in CLOSED state
        failure_count = 0
        redis.call('HSET', key, 'failure_count', 0)
    end
end

-- Set TTL to auto-cleanup (recovery_timeout + buffer)
redis.call('EXPIRE', key, math.ceil(recovery_timeout) + 60)

return {state, failure_count, success_count}
"""

# Lua 脚本：检查熔断器状态
# KEYS[1]: circuit breaker key
# ARGV[1]: current timestamp
# ARGV[2]: recovery_timeout
# Returns: [state, should_allow_call (1 or 0)]
LUA_CHECK_STATE = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local recovery_timeout = tonumber(ARGV[2])

local state = redis.call('HGET', key, 'state') or 'CLOSED'
local last_failure_time = tonumber(redis.call('HGET', key, 'last_failure_time')) or 0

if state == 'OPEN' then
    -- Check if recovery timeout has elapsed
    if now - last_failure_time >= recovery_timeout then
        -- Transition to HALF_OPEN
        redis.call('HSET', key, 'state', 'HALF_OPEN')
        redis.call('HSET', key, 'success_count', 0)
        return {'HALF_OPEN', 1}
    else
        return {'OPEN', 0}
    end
else
    -- CLOSED or HALF_OPEN: allow call
    return {state, 1}
end
"""


class DistributedCircuitBreakerMiddleware(BaseMiddleware):
    """
    分布式熔断器中间件（Redis 后端）。priority=175。
    
    使用 Redis Hash 存储熔断器状态，支持多实例共享熔断状态。
    通过 Lua 脚本保证状态转换的原子性，避免竞态条件。
    
    特性：
      - 分布式熔断器状态（多实例共享）
      - 原子性状态转换（Lua 脚本）
      - 自动过期清理（Redis TTL）
      - 支持监控多个 Provider
      - 降级策略（Redis 不可用时允许调用）
    
    状态机：
      CLOSED -> OPEN: 连续失败次数超过 failure_threshold
      OPEN -> HALF_OPEN: 经过 recovery_timeout 秒后
      HALF_OPEN -> CLOSED: 连续成功 success_threshold 次
      HALF_OPEN -> OPEN: 出现任何失败
    """

    priority: int = 175
    is_mandatory: bool = False

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
        key_prefix: str = "onion:cb",
        pool_size: int = 10,
        fallback_allow: bool = True,  # Redis 不可用时是否允许调用
    ) -> None:
        """
        Args:
            redis_url: Redis 连接 URL
            failure_threshold: 触发熔断的连续失败次数
            recovery_timeout: 熔断后恢复超时时间（秒）
            success_threshold: 半开状态下恢复所需的连续成功次数
            key_prefix: Redis key 前缀
            pool_size: Redis 连接池大小
            fallback_allow: Redis 不可用时是否允许调用（True=允许，False=拒绝）
        """
        try:
            import redis.asyncio as redis
        except ImportError as err:
            raise ImportError(
                "redis package is required: pip install redis>=5.0"
            ) from err

        self._redis_url = redis_url
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold
        self._key_prefix = key_prefix
        self._fallback_allow = fallback_allow
        
        self._lua_update_sha: str | None = None
        self._lua_check_sha: str | None = None
        
        # 跟踪已注册的 provider
        self._providers: set[str] = set()

        # 创建 Redis 连接池
        self._redis_pool = redis.ConnectionPool.from_url(
            redis_url,
            max_connections=pool_size,
            decode_responses=True,
            socket_connect_timeout=5.0,  # 防止启动时 hang
            socket_timeout=5.0,  # 防止操作时 hang
        )
        self._redis: redis.Redis | None = None

    def add_provider(self, provider_name: str) -> None:
        """注册需要监控的 Provider。"""
        self._providers.add(provider_name)
        logger.info("Registered provider '%s' for distributed circuit breaking", provider_name)

    async def startup(self) -> None:
        """初始化 Redis 连接并加载 Lua 脚本。"""
        import redis.asyncio as redis
        
        self._redis = redis.Redis(connection_pool=self._redis_pool)
        
        try:
            # 测试连接（redis.asyncio 的 ping() 始终是 coroutine）
            await self._redis.ping()  # type: ignore[misc]
            
            # 注册 Lua 脚本（script_load() 也始终是 coroutine）
            self._lua_update_sha = await self._redis.script_load(LUA_UPDATE_STATE)
            self._lua_check_sha = await self._redis.script_load(LUA_CHECK_STATE)
            
            logger.info(
                "DistributedCircuitBreakerMiddleware started | redis=%s | threshold=%d/%.0fs/%d",
                self._redis_url, self._failure_threshold, 
                self._recovery_timeout, self._success_threshold
            )
        except Exception as exc:
            logger.error("Failed to connect to Redis: %s", exc)
            if not self._fallback_allow:
                raise

    async def shutdown(self) -> None:
        """关闭 Redis 连接。"""
        if self._redis:
            await self._redis.aclose()
            logger.info("DistributedCircuitBreakerMiddleware stopped.")

    async def process_request(self, context: AgentContext) -> AgentContext:
        """请求前检查熔断器状态。"""
        # 从 metadata 中获取 provider 名称
        provider_name = context.metadata.get("provider_name", "default")
        
        if provider_name not in self._providers:
            # 未注册的 provider 不监控
            return context
        
        try:
            if not self._redis or not self._lua_check_sha:
                raise RuntimeError("Redis not initialized")
            
            key = f"{self._key_prefix}:{provider_name}"
            now = time.time()
            
            # 检查熔断器状态
            evalsha_result = self._redis.evalsha(
                self._lua_check_sha,
                1,
                key,
                str(now),
                str(self._recovery_timeout),
            )
            
            if isinstance(evalsha_result, (list, tuple)):
                result = evalsha_result
            else:
                result = await evalsha_result  # type: ignore[misc]
            
            state = result[0]
            should_allow = int(result[1])
            
            # 记录当前状态到 context
            context.metadata["circuit_breaker_state"] = state
            context.metadata["circuit_breaker_provider"] = provider_name
            
            if not should_allow:
                logger.warning(
                    "[%s] Circuit breaker OPEN for provider '%s'",
                    context.request_id, provider_name
                )
                raise CircuitBreakerError(
                    f"Circuit breaker for provider '{provider_name}' is OPEN. "
                    f"Retry after {self._recovery_timeout:.0f}s."
                )
            
            logger.debug(
                "[%s] Circuit breaker %s for provider '%s'",
                context.request_id, state, provider_name
            )
            
        except CircuitBreakerError:
            raise
        except Exception as exc:
            logger.error("[%s] Redis error: %s", context.request_id, exc)
            if not self._fallback_allow:
                raise CircuitBreakerError(
                    f"Circuit breaker unavailable: {exc}"
                ) from exc
            # fallback_allow=True: 允许调用继续
        
        return context

    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse:
        """响应后记录成功。"""
        provider_name = context.metadata.get("circuit_breaker_provider")
        
        if provider_name and provider_name in self._providers:
            await self._record_success(provider_name, context.request_id)
        
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
        """错误时记录失败。"""
        provider_name = context.metadata.get("circuit_breaker_provider")
        
        if provider_name and provider_name in self._providers:
            await self._record_failure(provider_name, context.request_id, error)

    async def _record_success(self, provider_name: str, request_id: str) -> None:
        """记录成功调用。"""
        if not self._redis or not self._lua_update_sha:
            return
        
        try:
            key = f"{self._key_prefix}:{provider_name}"
            now = time.time()
            
            evalsha_result = self._redis.evalsha(
                self._lua_update_sha,
                1,
                key,
                "success",
                str(now),
                str(self._failure_threshold),
                str(self._recovery_timeout),
                str(self._success_threshold),
            )
            
            if not isinstance(evalsha_result, (list, tuple)):
                await evalsha_result  # type: ignore[misc]
            
            logger.debug(
                "[%s] Recorded success for provider '%s'",
                request_id, provider_name
            )
        except Exception as exc:
            logger.error("[%s] Failed to record success: %s", request_id, exc)

    async def _record_failure(
        self, provider_name: str, request_id: str, error: Exception
    ) -> None:
        """记录失败调用。"""
        if not self._redis or not self._lua_update_sha:
            return
        
        try:
            key = f"{self._key_prefix}:{provider_name}"
            now = time.time()
            
            evalsha_result = self._redis.evalsha(
                self._lua_update_sha,
                1,
                key,
                "failure",
                str(now),
                str(self._failure_threshold),
                str(self._recovery_timeout),
                str(self._success_threshold),
            )
            
            if isinstance(evalsha_result, (list, tuple)):
                result = evalsha_result
            else:
                result = await evalsha_result  # type: ignore[misc]
            
            new_state = result[0]
            failure_count = int(result[1])
            
            logger.warning(
                "[%s] Recorded failure for provider '%s' (state=%s, failures=%d)",
                request_id, provider_name, new_state, failure_count
            )
        except Exception as exc:
            logger.error("[%s] Failed to record failure: %s", request_id, exc)

    async def get_status(self, provider_name: str) -> dict[str, Any]:
        """
        获取指定 provider 的熔断器状态。
        
        Returns:
            包含熔断器状态的字典
        """
        if not self._redis:
            raise RuntimeError("Redis not initialized")
        
        key = f"{self._key_prefix}:{provider_name}"
        
        try:
            state_result = await self._redis.hget(key, "state")  # type: ignore[misc]
            state = state_result if state_result else "CLOSED"
            
            failure_count_result = await self._redis.hget(key, "failure_count")  # type: ignore[misc]
            failure_count = int(failure_count_result) if failure_count_result else 0
            
            success_count_result = await self._redis.hget(key, "success_count")  # type: ignore[misc]
            success_count = int(success_count_result) if success_count_result else 0
            
            return {
                "provider": provider_name,
                "state": state,
                "failure_count": failure_count,
                "success_count": success_count,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
                "distributed": True,
            }
        except Exception as exc:
            logger.error("Failed to get status for provider %s: %s", provider_name, exc)
            return {
                "provider": provider_name,
                "error": str(exc),
                "distributed": True,
            }

    async def reset(self, provider_name: str) -> None:
        """重置指定 provider 的熔断器状态。"""
        if not self._redis:
            raise RuntimeError("Redis not initialized")
        
        key = f"{self._key_prefix}:{provider_name}"
        await self._redis.delete(key)
        logger.info("Circuit breaker reset for provider '%s'", provider_name)
