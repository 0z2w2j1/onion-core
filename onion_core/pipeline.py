"""
Onion Core - Pipeline（核心调度引擎）

阶段三+四：
  - 相对导入，可作为包安装
  - provider.complete() / stream() 独立超时控制
  - max_retries + 指数退避重试
  - startup 部分失败回滚（已启动的中间件会被 shutdown）
  - stream 中途错误清理 metadata 缓冲区
  - _started 标志用 asyncio.Lock 保护，防止并发双重初始化
  - RetryPolicy 替代字符串名称异常判断
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import random
import threading
import types
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Iterator
from typing import Any, TypeVar, cast, overload

from .base import BaseMiddleware
from .circuit_breaker import CircuitBreaker
from .config import OnionConfig
from .error_codes import ErrorCode
from .models import (
    _MAX_TOOL_CALL_DEPTH,
    AgentContext,
    CacheHitException,
    CircuitBreakerError,
    LLMResponse,
    RetryOutcome,
    RetryPolicy,
    StreamChunk,
    ToolCall,
    ToolResult,
    ValidationError,
)
from .provider import LLMProvider

logger = logging.getLogger("onion_core.pipeline")

# 输入验证常量（防止 DoS）
_MAX_MESSAGES = 1000  # 最多 1000 条消息，防止内存溢出
_MAX_CONTENT_LENGTH = 1_000_000  # 单条消息最大 1MB，防止超大 payload
_MAX_NESTING_LEVEL = 5  # 消息内容最大嵌套层级
_UNICODE_COMBINING_THRESHOLD = 0.3  # Unicode 组合字符阈值（30%）

_DEFAULT_RETRY_POLICY = RetryPolicy()

_T = TypeVar("_T")


def _detect_unicode_bomb(text: str) -> bool:
    """
    检测 Unicode 炸弹（Zalgo 文本等）。

    检查组合字符（combining characters）比例是否超过阈值。
    Zalgo 文本通过大量组合字符实现“溢出”效果，可能导致渲染引擎崩溃。

    Args:
        text: 待检测的文本

    Returns:
        True 如果检测到 Unicode 炸弹
    """
    if not text:
        return False

    combining_count = sum(1 for c in text if unicodedata.combining(c))
    total_chars = len(text)

    if total_chars == 0:
        return False

    ratio = combining_count / total_chars
    return ratio > _UNICODE_COMBINING_THRESHOLD


class Pipeline:
    """
    Onion Core 核心调度引擎。

    用法：
        async with Pipeline(provider=MyProvider(), name="my-pipeline") as p:
            p.add_middleware(ObservabilityMiddleware())
            p.add_middleware(SafetyGuardrailMiddleware())
            response = await p.run(context)

    Fallback Provider 用法：
        async with Pipeline(provider=primary, fallback_providers=[backup1, backup2]) as p:
            response = await p.run(context)
    """

    def __init__(
        self,
        provider: LLMProvider,
        name: str = "default",
        middleware_timeout: float | None = None,
        provider_timeout: float | None = None,
        total_timeout: float | None = None,
        max_retries: int = 0,
        retry_base_delay: float = 0.5,
        fallback_providers: list[LLMProvider] | None = None,
        retry_policy: RetryPolicy | None = None,
        enable_circuit_breaker: bool = True,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
        max_stream_chunks: int = 10000,
        owns_provider: bool = True,
    ) -> None:
        """
        Args:
            provider: 主 LLM Provider 实例
            name: Pipeline 实例名称，用于 Metrics/Traces 标签
            middleware_timeout: 单个中间件调用超时（秒），None 不限制
            provider_timeout: provider.complete() / stream() 超时（秒），None 不限制
            total_timeout: 整个请求的总超时（包括所有中间件 + provider 调用），None 不限制
            max_retries: provider 调用失败时的最大重试次数（指数退避）
            retry_base_delay: 重试基础延迟（秒），实际延迟 = base * 2^attempt + jitter
            fallback_providers: 主 provider 全部重试失败后依次尝试的备用 provider 列表
            retry_policy: 自定义重试决策器，默认使用 RetryPolicy()
            enable_circuit_breaker: 是否启用熔断机制
            circuit_failure_threshold: 熔断触发阈值（连续失败次数）
            circuit_recovery_timeout: 熔断恢复超时（秒）
            max_stream_chunks: 流式响应最大 chunk 数，防止 DoS 攻击（默认 10000）
            owns_provider: 是否由 Pipeline 管理 Provider 生命周期（调用 cleanup）
        """
        self.name = name
        self._provider = provider
        self._fallback_providers: list[LLMProvider] = fallback_providers or []
        self._middleware_timeout = middleware_timeout
        self._provider_timeout = provider_timeout
        self._total_timeout = total_timeout
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_policy = retry_policy or _DEFAULT_RETRY_POLICY
        self._max_stream_chunks = max_stream_chunks
        self._owns_provider = owns_provider

        # 熔断器配置
        self._enable_circuit_breaker = enable_circuit_breaker
        self._circuit_breakers: dict[int, CircuitBreaker] = {}
        # 为每个 provider 分配稳定索引，避免使用 id() 作为字典键
        self._provider_indices: dict[int, int] = {}
        if enable_circuit_breaker:
            all_providers = [self._provider] + self._fallback_providers
            for idx, p in enumerate(all_providers):
                p_name = f"{type(p).__name__}#{idx}"
                self._provider_indices[id(p)] = idx
                self._circuit_breakers[idx] = CircuitBreaker(
                    name=p_name,
                    failure_threshold=circuit_failure_threshold,
                    recovery_timeout=circuit_recovery_timeout,
                )

        self._lock = asyncio.Lock()
        self._middlewares: list[BaseMiddleware] = []
        self._sorted_cache: list[BaseMiddleware] | None = None
        self._started = False

    # ------------------------------------------------------------------
    # 中间件注册
    # ------------------------------------------------------------------

    def add_middleware(self, middleware: BaseMiddleware) -> Pipeline:
        """注册中间件，支持链式调用。应在 startup() 前完成。"""
        self._middlewares.append(middleware)
        self._sorted_cache = None
        logger.info("Middleware registered: %s (priority=%d)", middleware.name, middleware.priority)
        return self

    async def add_middleware_async(self, middleware: BaseMiddleware) -> Pipeline:
        """运行时并发安全注册中间件。"""
        async with self._lock:
            self._middlewares.append(middleware)
            self._sorted_cache = None
        logger.info(
            "Middleware registered (async): %s (priority=%d)", middleware.name, middleware.priority
        )
        if self._started:
            await middleware.startup()
        return self

    def _get_sorted_middlewares(self) -> list[BaseMiddleware]:
        if self._sorted_cache is None:
            self._sorted_cache = sorted(self._middlewares, key=lambda mw: mw.priority)
        return self._sorted_cache

    @property
    def middlewares(self) -> list[BaseMiddleware]:
        return list(self._get_sorted_middlewares())

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """
        启动 Pipeline。若某个中间件 startup 失败，已启动的中间件会被回滚 shutdown。
        """
        async with self._lock:
            if self._started:
                logger.warning("Pipeline.startup() called more than once, skipping.")
                return

            started: list[BaseMiddleware] = []
            logger.info(
                "Pipeline '%s' starting up (%d middlewares)...", self.name, len(self._middlewares)
            )

            for mw in self._get_sorted_middlewares():
                try:
                    await mw.startup()
                    started.append(mw)
                    logger.debug("Middleware started: %s", mw.name)
                except Exception as exc:
                    logger.error(
                        "Middleware '%s' failed during startup: %s — rolling back", mw.name, exc
                    )
                    for started_mw in reversed(started):
                        try:
                            await started_mw.shutdown()
                        except Exception as inner:
                            logger.warning(
                                "Rollback shutdown failed for '%s': %s", started_mw.name, inner
                            )
                    raise

            self._started = True
            logger.info("Pipeline '%s' started.", self.name)

    async def shutdown(self) -> None:
        """关闭 Pipeline，逆序 shutdown 所有中间件，单个失败不中断其余。"""
        async with self._lock:
            if not self._started:
                return

            logger.info("Pipeline '%s' shutting down...", self.name)
            errors = []
            for mw in reversed(self._get_sorted_middlewares()):
                try:
                    await mw.shutdown()
                    logger.debug("Middleware stopped: %s", mw.name)
                except Exception as exc:
                    logger.error("Middleware '%s' failed during shutdown: %s", mw.name, exc)
                    errors.append((mw.name, exc))

            # 释放 Provider 资源（HTTP 连接等）
            if self._owns_provider:
                for p in [self._provider] + self._fallback_providers:
                    try:
                        cleanup_fn = getattr(p, "cleanup", None)
                        if cleanup_fn is not None and asyncio.iscoroutinefunction(cleanup_fn):
                            await cleanup_fn()
                            logger.debug("Provider '%s' cleaned up.", type(p).__name__)
                        else:
                            logger.debug("Provider '%s' has no async cleanup.", type(p).__name__)
                    except Exception as exc:
                        logger.error("Provider '%s' cleanup failed: %s", type(p).__name__, exc)
                        errors.append((type(p).__name__, exc))

            self._started = False
            logger.info("Pipeline '%s' stopped.", self.name)

            if errors:
                names = ", ".join(n for n, _ in errors)
                raise RuntimeError(f"Shutdown errors in middlewares: {names}")

    async def __aenter__(self) -> Pipeline:
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        try:
            await self.shutdown()
        except Exception as exc:
            logger.exception("Pipeline shutdown error during __aexit__: %s", exc)

    # ------------------------------------------------------------------
    # 公开调用入口
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> LLMResponse:
        """非流式完整调用：request → provider.complete → response。"""
        self._validate_context(context)
        
        if self._total_timeout is not None:
            try:
                return await asyncio.wait_for(
                    self._run_with_cache_handling(context),
                    timeout=self._total_timeout,
                )
            except TimeoutError:
                raise TimeoutError(
                    f"Pipeline total timeout ({self._total_timeout}s) exceeded for request {context.request_id}"
                ) from None
        else:
            return await self._run_with_cache_handling(context)
    
    async def _run_with_cache_handling(self, context: AgentContext) -> LLMResponse:
        """内部方法：处理缓存命中逻辑。"""
        try:
            context = await self._run_request(context)
        except CacheHitException as exc:
            # 缓存命中，直接返回缓存的响应
            logger.info(
                "[%s] Returning cached response, skipping provider call",
                context.request_id,
            )
            return await self._run_response(context, exc.cached_response)

        raw_response = await self._call_provider_with_retry(context)
        return await self._run_response(context, raw_response)

    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        """流式调用：request → provider.stream → 逐 chunk 过中间件。"""
        self._validate_context(context)
        
        buf_key = f"_safety_buf_{context.request_id}"
        timestamp_key = f"_safety_buf_ts_{context.request_id}"
        
        try:
            if self._total_timeout is not None:
                # 使用 deadline 机制实现总超时
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    raise RuntimeError(
                        "stream() must be called from within an async context. "
                        "Use stream_sync() for synchronous usage."
                    ) from None
                deadline = loop.time() + self._total_timeout
                
                async for chunk in self._stream_with_deadline(context, deadline):
                    yield chunk
            else:
                async for chunk in self._stream_without_deadline(context):
                    yield chunk
        finally:
            # 确保在任何情况下（包括异常）都清理缓冲区
            context.metadata.pop(buf_key, None)
            context.metadata.pop(timestamp_key, None)
    
    async def _stream_with_deadline(self, context: AgentContext, deadline: float) -> AsyncIterator[StreamChunk]:
        """内部方法：带总超时的流式调用。"""
        buf_key = f"_safety_buf_{context.request_id}"
        timestamp_key = f"_safety_buf_ts_{context.request_id}"
        chunk_count = 0
        try:
            context = await self._run_request(context)
        except CacheHitException:
            # 缓存命中 - 流式不支持缓存，记录警告
            logger.warning(
                "[%s] Cache hit in stream mode (not supported), falling back to provider",
                context.request_id,
            )
            # 继续执行 provider 调用

        async def _provider_gen() -> AsyncIterator[StreamChunk]:
            async for chunk in self._provider.stream(context):
                yield chunk

        gen = _provider_gen()
        while True:
            try:
                # 计算剩余时间
                loop = asyncio.get_running_loop()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Pipeline total timeout ({self._total_timeout}s) exceeded for stream request {context.request_id}"
                    )

                raw_chunk = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                break

            # 检查 chunk 数量防止 DoS
            chunk_count += 1
            if chunk_count > self._max_stream_chunks:
                raise ValidationError(
                    f"Stream exceeded max chunks limit: {chunk_count} > {self._max_stream_chunks}"
                )

            chunk = await self._run_stream_chunk(context, raw_chunk)
            yield chunk
        
        # 正常结束时清理缓冲区
        context.metadata.pop(buf_key, None)
        context.metadata.pop(timestamp_key, None)
    
    async def _stream_without_deadline(self, context: AgentContext) -> AsyncIterator[StreamChunk]:
        """内部方法：无总超时的流式调用（原有逻辑）。"""
        buf_key = f"_safety_buf_{context.request_id}"
        timestamp_key = f"_safety_buf_ts_{context.request_id}"
        chunk_count = 0
        try:
            context = await self._run_request(context)
        except CacheHitException:
            # 缓存命中 - 流式不支持缓存，记录警告
            logger.warning(
                "[%s] Cache hit in stream mode (not supported), falling back to provider",
                context.request_id,
            )
            # 继续执行 provider 调用

        async def _provider_gen() -> AsyncIterator[StreamChunk]:
            async for chunk in self._provider.stream(context):
                yield chunk

        if self._provider_timeout is not None:
            # 计算绝对截止时间，确保总超时而非每 chunk 超时
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                raise RuntimeError(
                    "stream() must be called from within an async context. "
                    "Use stream_sync() for synchronous usage."
                ) from None
            deadline = loop.time() + self._provider_timeout

            gen = _provider_gen()
            while True:
                try:
                    # 计算剩余时间
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Stream timeout exceeded ({self._provider_timeout}s)"
                        )

                    raw_chunk = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break

                # 检查 chunk 数量防止 DoS
                chunk_count += 1
                if chunk_count > self._max_stream_chunks:
                    raise ValidationError(
                        f"Stream exceeded max chunks limit: {chunk_count} > {self._max_stream_chunks}"
                    )

                chunk = await self._run_stream_chunk(context, raw_chunk)
                yield chunk
        else:
            async for raw_chunk in self._provider.stream(context):
                # 检查 chunk 数量防止 DoS
                chunk_count += 1
                if chunk_count > self._max_stream_chunks:
                    raise ValidationError(
                        f"Stream exceeded max chunks limit: {chunk_count} > {self._max_stream_chunks}"
                    )

                chunk = await self._run_stream_chunk(context, raw_chunk)
                yield chunk
        
        # 正常结束时清理缓冲区
        context.metadata.pop(buf_key, None)
        context.metadata.pop(timestamp_key, None)

    async def execute_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        return await self._run_tool_call(context, tool_call)

    async def execute_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult:
        return await self._run_tool_result(context, result)

    # ------------------------------------------------------------------
    # Provider 调用（超时 + 重试）
    # ------------------------------------------------------------------

    async def _call_provider_with_retry(self, context: AgentContext) -> LLMResponse:
        """带超时、熔断和指数退避重试的 provider.complete() 调用。
        主 provider 全部重试失败后，依次尝试 fallback_providers。
        """
        all_providers = [self._provider] + self._fallback_providers
        exceptions: list[tuple[str, Exception]] = []

        for provider_idx, provider in enumerate(all_providers):
            is_fallback = provider_idx > 0
            cb_idx = self._provider_indices.get(id(provider), provider_idx)
            cb = self._circuit_breakers.get(cb_idx)
            provider_name = f"{type(provider).__name__}#{provider_idx}"

            if is_fallback:
                logger.warning(
                    "[%s][pipeline=%s] Switching to fallback provider #%d: %s",
                    context.request_id,
                    self.name,
                    provider_idx,
                    type(provider).__name__,
                )

            # 检查熔断状态
            if cb:
                try:
                    await cb.check_call()
                except CircuitBreakerError as cb_exc:
                    logger.warning(
                        "[%s][pipeline=%s] Provider #%d is circuit-broken, skipping",
                        context.request_id,
                        self.name,
                        provider_idx,
                    )
                    exceptions.append((provider_name, cb_exc))
                    continue  # 尝试下一个 fallback

            for attempt in range(self._max_retries + 1):
                try:
                    if self._provider_timeout is not None:
                        resp = await asyncio.wait_for(
                            provider.complete(context),
                            timeout=self._provider_timeout,
                        )
                    else:
                        resp = await provider.complete(context)

                    # 调用成功，记录熔断器成功
                    if cb:
                        await cb.record_success()
                    return resp

                except Exception as exc:
                    outcome = self._retry_policy.classify(exc)

                    # 记录熔断器失败（仅对非 FATAL 异常记录，因为 FATAL 通常是业务/参数错误，不是 Provider 故障）
                    if cb and outcome != RetryOutcome.FATAL:
                        await cb.record_failure()

                    if outcome == RetryOutcome.FATAL:
                        # 彻底失败，立即抛出，不尝试 fallback
                        raise

                    if outcome == RetryOutcome.FALLBACK:
                        # 跳过当前 provider 的剩余重试，直接尝试下一个 fallback
                        logger.warning(
                            "[%s][pipeline=%s] Provider[%d] non-retryable (%s), trying fallback",
                            context.request_id,
                            self.name,
                            provider_idx,
                            type(exc).__name__,
                        )
                        exceptions.append((provider_name, exc))
                        break  # 跳出 attempt 循环，进入下一个 provider

                    # RETRY
                    if attempt < self._max_retries:
                        delay = self._retry_base_delay * (2**attempt) + random.uniform(0, 0.1)
                        logger.warning(
                            "[%s][pipeline=%s] Provider[%d] call failed (attempt %d/%d): %s — retrying in %.2fs",
                            context.request_id,
                            self.name,
                            provider_idx,
                            attempt + 1,
                            self._max_retries + 1,
                            exc,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[%s][pipeline=%s] Provider[%d] failed after %d attempts: %s",
                            context.request_id,
                            self.name,
                            provider_idx,
                            self._max_retries + 1,
                            exc,
                        )
                        exceptions.append((provider_name, exc))

        # 所有 provider 都失败，聚合异常信息
        if exceptions:
            error_summary = "; ".join(
                f"{name}: {type(exc).__name__}({exc})" for name, exc in exceptions
            )
            logger.error(
                "[%s][pipeline=%s] All providers failed: %s",
                context.request_id,
                self.name,
                error_summary,
            )
            # 使用最后一个异常作为主异常，保留完整上下文
            last_exc = exceptions[-1][1]
            raise last_exc

        raise RuntimeError("Unexpected state: no providers were attempted")  # pragma: no cover

    # ------------------------------------------------------------------
    # 内部调度
    # ------------------------------------------------------------------

    def _validate_context(self, context: AgentContext) -> None:
        """
        验证 AgentContext 的合法性。

        防止恶意用户构造超大 payload、Unicode 炸弹等导致 DoS。

        Raises:
            ValidationError: 当验证失败时抛出
        """
        # 验证消息数量
        if len(context.messages) > _MAX_MESSAGES:
            raise ValidationError(
                f"Too many messages: {len(context.messages)} (max: {_MAX_MESSAGES})",
                error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
            )

        # 验证每条消息的内容
        for i, msg in enumerate(context.messages):
            if isinstance(msg.content, str):
                # 检查内容长度
                if len(msg.content) > _MAX_CONTENT_LENGTH:
                    raise ValidationError(
                        f"Message {i} content too long: {len(msg.content)} chars "
                        f"(max: {_MAX_CONTENT_LENGTH})",
                        error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                    )

                # 检查 Unicode 炸弹
                if _detect_unicode_bomb(msg.content):
                    raise ValidationError(
                        f"Message {i} contains suspicious Unicode characters (possible Zalgo text)",
                        error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                    )

            elif isinstance(msg.content, list):
                # 多模态内容
                total_length = sum(
                    len(block.text) if block.text else 0
                    for block in msg.content
                    if block.type == "text"
                )
                if total_length > _MAX_CONTENT_LENGTH:
                    raise ValidationError(
                        f"Message {i} multimodal content too long: {total_length} chars "
                        f"(max: {_MAX_CONTENT_LENGTH})",
                        error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                    )

                # 检查嵌套深度
                if len(msg.content) > _MAX_NESTING_LEVEL:
                    raise ValidationError(
                        f"Message {i} content blocks too nested: {len(msg.content)} levels "
                        f"(max: {_MAX_NESTING_LEVEL})",
                        error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                    )

                # 检查每个文本块的 Unicode 炸弹
                for block_idx, block in enumerate(msg.content):
                    if block.type == "text" and block.text and _detect_unicode_bomb(block.text):
                        raise ValidationError(
                            f"Message {i} block {block_idx} contains suspicious Unicode characters",
                            error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                        )

        # 验证工具调用的嵌套深度
        if context.metadata.get("tool_calls_depth", 0) > _MAX_TOOL_CALL_DEPTH:
            raise ValidationError(
                f"Tool call nesting depth exceeded: {context.metadata['tool_calls_depth']} "
                f"(max: {_MAX_TOOL_CALL_DEPTH})",
                error_code=ErrorCode.VALIDATION_INVALID_TOOL_CALL,
            )

    @overload
    async def _call_middleware(
        self, coro: Awaitable[AgentContext], mw: BaseMiddleware | None = None
    ) -> AgentContext: ...

    @overload
    async def _call_middleware(
        self, coro: Awaitable[LLMResponse], mw: BaseMiddleware | None = None
    ) -> LLMResponse: ...

    @overload
    async def _call_middleware(
        self, coro: Awaitable[StreamChunk], mw: BaseMiddleware | None = None
    ) -> StreamChunk: ...

    @overload
    async def _call_middleware(
        self, coro: Awaitable[ToolCall], mw: BaseMiddleware | None = None
    ) -> ToolCall: ...

    @overload
    async def _call_middleware(
        self, coro: Awaitable[ToolResult], mw: BaseMiddleware | None = None
    ) -> ToolResult: ...

    @overload
    async def _call_middleware(
        self, coro: Awaitable[_T], mw: BaseMiddleware | None = None
    ) -> _T: ...

    async def _call_middleware(self, coro: Awaitable[_T], mw: BaseMiddleware | None = None) -> _T:
        timeout = (
            mw.timeout if mw is not None and mw.timeout is not None else self._middleware_timeout
        )
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    async def _run_request(self, context: AgentContext) -> AgentContext:
        for mw in self._get_sorted_middlewares():
            try:
                result = await self._call_middleware(mw.process_request(context), mw)
                if result is None:
                    raise RuntimeError(f"Middleware '{mw.name}' aborted the request chain")
                context = result
            except CacheHitException:
                # 缓存命中是正常流程，不是错误，直接向上抛出
                raise
            except Exception as exc:
                logger.error(
                    "[%s][pipeline=%s] '%s'.process_request raised %s: %s",
                    context.request_id,
                    self.name,
                    mw.name,
                    type(exc).__name__,
                    exc,
                )
                await self._notify_error(context, exc)
                # 链路拦截类异常（安全/限流）或强制性中间件失败必须传播，其余隔离继续
                if self._retry_policy.is_chain_breaking(exc) or mw.is_mandatory:
                    raise
                logger.warning(
                    "[%s][pipeline=%s] '%s'.process_request isolated, continuing chain",
                    context.request_id,
                    self.name,
                    mw.name,
                )
        return context

    async def _run_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse:
        for mw in reversed(self._get_sorted_middlewares()):
            try:
                response = await self._call_middleware(mw.process_response(context, response), mw)
            except Exception as exc:
                logger.error(
                    "[%s][pipeline=%s] '%s'.process_response raised %s: %s",
                    context.request_id,
                    self.name,
                    mw.name,
                    type(exc).__name__,
                    exc,
                )
                await self._notify_error(context, exc)
                if self._retry_policy.is_chain_breaking(exc) or mw.is_mandatory:
                    raise
                logger.warning(
                    "[%s][pipeline=%s] '%s'.process_response isolated, continuing chain",
                    context.request_id,
                    self.name,
                    mw.name,
                )
        return response

    async def _run_stream_chunk(self, context: AgentContext, chunk: StreamChunk) -> StreamChunk:
        for mw in reversed(self._get_sorted_middlewares()):
            try:
                chunk = await self._call_middleware(mw.process_stream_chunk(context, chunk), mw)
            except Exception as exc:
                logger.error(
                    "[%s][pipeline=%s] '%s'.process_stream_chunk raised %s: %s",
                    context.request_id,
                    self.name,
                    mw.name,
                    type(exc).__name__,
                    exc,
                )
                await self._notify_error(context, exc)
                if self._retry_policy.is_chain_breaking(exc) or mw.is_mandatory:
                    raise
                logger.warning(
                    "[%s][pipeline=%s] '%s'.process_stream_chunk isolated, continuing chain",
                    context.request_id,
                    self.name,
                    mw.name,
                )
        return chunk

    async def _run_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        for mw in self._get_sorted_middlewares():
            try:
                tool_call = await self._call_middleware(mw.on_tool_call(context, tool_call), mw)
            except Exception as exc:
                logger.error(
                    "[%s][pipeline=%s] '%s'.on_tool_call blocked '%s': %s",
                    context.request_id,
                    self.name,
                    mw.name,
                    tool_call.name,
                    exc,
                )
                await self._notify_error(context, exc)
                if self._retry_policy.is_chain_breaking(exc) or mw.is_mandatory:
                    raise
                logger.warning(
                    "[%s][pipeline=%s] '%s'.on_tool_call isolated, continuing chain",
                    context.request_id,
                    self.name,
                    mw.name,
                )
        return tool_call

    async def _run_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult:
        for mw in reversed(self._get_sorted_middlewares()):
            try:
                result = await self._call_middleware(mw.on_tool_result(context, result), mw)
            except Exception as exc:
                logger.error(
                    "[%s][pipeline=%s] '%s'.on_tool_result raised %s: %s",
                    context.request_id,
                    self.name,
                    mw.name,
                    type(exc).__name__,
                    exc,
                )
                await self._notify_error(context, exc)
                if self._retry_policy.is_chain_breaking(exc) or mw.is_mandatory:
                    raise
                logger.warning(
                    "[%s][pipeline=%s] '%s'.on_tool_result isolated, continuing chain",
                    context.request_id,
                    self.name,
                    mw.name,
                )
        return result

    async def _notify_error(self, context: AgentContext, error: Exception) -> None:
        for mw in self._get_sorted_middlewares():
            try:
                await mw.on_error(context, error)
            except Exception as inner:
                logger.warning(
                    "[%s][pipeline=%s] '%s'.on_error itself raised: %s",
                    context.request_id,
                    self.name,
                    mw.name,
                    inner,
                )

    @classmethod
    def from_config(
        cls,
        provider: LLMProvider,
        config: OnionConfig,
        name: str = "default",
    ) -> Pipeline:
        """
        从 OnionConfig 构建 Pipeline，自动配置内置中间件。

        用法：
            cfg = OnionConfig.from_file("onion.json")
            pipeline = Pipeline.from_config(provider=MyProvider(), config=cfg)
        """
        from .middlewares.context import ContextWindowMiddleware
        from .middlewares.observability import ObservabilityMiddleware
        from .middlewares.safety import SafetyGuardrailMiddleware

        p = cls(
            provider=provider,
            name=name,
            middleware_timeout=config.pipeline.middleware_timeout,
            provider_timeout=config.pipeline.provider_timeout,
            max_retries=config.pipeline.max_retries,
            enable_circuit_breaker=config.pipeline.enable_circuit_breaker,
            circuit_failure_threshold=config.pipeline.circuit_failure_threshold,
            circuit_recovery_timeout=config.pipeline.circuit_recovery_timeout,
            max_stream_chunks=config.pipeline.max_stream_chunks,
        )

        p.add_middleware(ObservabilityMiddleware())
        p.add_middleware(
            SafetyGuardrailMiddleware(
                blocked_keywords=config.safety.blocked_keywords or None,
                blocked_tools=config.safety.blocked_tools or None,
                enable_builtin_pii=config.safety.enable_pii_masking,
            )
        )
        p.add_middleware(
            ContextWindowMiddleware(
                max_tokens=config.context_window.max_tokens,
                keep_rounds=config.context_window.keep_rounds,
                encoding_name=config.context_window.encoding_name,
                summary_strategy=config.context_window.summary_strategy,
            )
        )
        return p

    # ------------------------------------------------------------------
    # 同步 API 封装
    # ------------------------------------------------------------------

    def _run_async_in_sync(self, coro: Awaitable[_T]) -> _T:
        """
        在同步环境中安全运行异步协程。

        策略：
          - 若无运行中的事件循环，直接使用 asyncio.run()
          - 若已有事件循环（如在 async 函数中调用），抛出明确错误
            避免线程池嵌套导致的死锁和资源泄露风险
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中的 loop，安全使用 asyncio.run()
            return asyncio.run(coro)  # type: ignore[arg-type]

        # 已有事件循环，禁止同步调用以避免死锁
        raise RuntimeError(
            "Cannot call sync methods from within an async context. "
            "Use 'await pipeline.run()' or other async methods instead. "
            "Sync methods are only for non-async environments (e.g., Flask/Django views)."
        )

    def run_sync(self, context: AgentContext) -> LLMResponse:
        """
        同步版本的 run() 方法，适用于非异步环境（如 Flask/Django）。

        注意：不能在 async 函数中调用此方法，否则会抛出 RuntimeError。

        用法：
            with Pipeline(provider=MyProvider()) as p:
                response = p.run_sync(context)
        """
        return self._run_async_in_sync(self.run(context))

    def stream_sync(self, context: AgentContext) -> Iterator[StreamChunk]:
        """
        同步版本的 stream() 方法，将异步生成器包装为同步生成器。

        使用单一线程和事件循环，避免每个 chunk 都跨线程切换的性能问题。
        
        注意：
          - 不能在 async 函数中调用此方法
          - 生成器会独占一个线程直到流式响应结束

        用法：
            with Pipeline(provider=MyProvider()) as p:
                for chunk in p.stream_sync(context):
                    print(chunk.delta, end="", flush=True)
        """
        # 检查是否在 async 上下文中
        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                "Cannot call stream_sync() from within an async context. "
                "Use 'async for chunk in pipeline.stream()' instead."
            )
        except RuntimeError as exc:
            if "no running event loop" not in str(exc):
                raise

        # 生产者线程 + 线程安全队列，避免一次性聚合全部 chunk
        stream_queue: queue.Queue[object] = queue.Queue(maxsize=64)
        sentinel = object()
        error_sentinel = object()
        stop_event = threading.Event()
        loop = asyncio.new_event_loop()
        producer_task: asyncio.Task[None] | None = None

        def _put_with_stop(item: object) -> bool:
            while not stop_event.is_set():
                try:
                    stream_queue.put(item, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        async def _producer() -> None:
            try:
                async for chunk in self.stream(context):
                    if stop_event.is_set():
                        break
                    if not _put_with_stop(chunk):
                        return
            except GeneratorExit:
                pass

        def _producer_runner() -> None:
            nonlocal producer_task
            asyncio.set_event_loop(loop)
            try:
                producer_task = loop.create_task(_producer())
                loop.run_until_complete(producer_task)
            except (Exception, asyncio.CancelledError) as exc:
                # 捕获 CancelledError 和其他异常，防止线程崩溃
                if not stop_event.is_set():
                    _put_with_stop((error_sentinel, exc))
            finally:
                # 清理 Provider 资源（关闭 HTTP 连接）
                async def _cleanup() -> None:
                    if hasattr(self._provider, 'cleanup'):
                        await self._provider.cleanup()
                    for fallback in self._fallback_providers:
                        if hasattr(fallback, 'cleanup'):
                            await fallback.cleanup()
                
                with contextlib.suppress(Exception):
                    loop.run_until_complete(_cleanup())
                
                _put_with_stop(sentinel)
                with contextlib.suppress(Exception):
                    loop.run_until_complete(loop.shutdown_asyncgens())
                with contextlib.suppress(Exception):
                    loop.close()

        worker = threading.Thread(target=_producer_runner, name="pipeline-stream-sync", daemon=True)
        worker.start()

        try:
            while True:
                item = stream_queue.get()
                if item is sentinel:
                    break
                if isinstance(item, tuple) and len(item) == 2 and item[0] is error_sentinel:
                    raise item[1]
                yield cast(StreamChunk, item)
        finally:
            stop_event.set()
            if producer_task is not None and not producer_task.done():
                with contextlib.suppress(Exception):
                    loop.call_soon_threadsafe(producer_task.cancel)
            
            # 等待工作线程结束，超时后记录警告
            worker.join(timeout=5.0)
            if worker.is_alive():
                logger.warning(
                    "stream_sync worker thread '%s' did not terminate within 5s timeout. "
                    "This may indicate a resource leak.",
                    worker.name,
                )
                # 不强制终止 daemon 线程，但记录警告供排查

    def execute_tool_call_sync(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
        """同步版本的 execute_tool_call()。"""
        return self._run_async_in_sync(self.execute_tool_call(context, tool_call))

    def execute_tool_result_sync(self, context: AgentContext, result: ToolResult) -> ToolResult:
        """同步版本的 execute_tool_result()。"""
        return self._run_async_in_sync(self.execute_tool_result(context, result))

    def startup_sync(self) -> None:
        """同步版本的 startup()。"""
        self._run_async_in_sync(self.startup())

    def shutdown_sync(self) -> None:
        """同步版本的 shutdown()。"""
        self._run_async_in_sync(self.shutdown())

    def __enter__(self) -> Pipeline:
        """支持同步上下文管理器协议。"""
        self.startup_sync()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """同步上下文管理器退出。"""
        self.shutdown_sync()

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """
        返回 Pipeline 的健康状态信息。

        Returns:
            包含健康状态的字典，结构如下：
            {
                "status": "healthy" | "not_started" | "degraded",
                "name": str,
                "started": bool,
                "middlewares_count": int,
                "provider": str,
                "fallback_providers": list[str],
                "circuit_breakers": dict[str, str],
            }

        用法：
            health = pipeline.health_check()
            if health["status"] != "healthy":
                logger.warning("Pipeline degraded: %s", health)
        """
        from .models import CircuitState

        cb_states: dict[str, str] = {}
        degraded = False

        all_providers = [self._provider] + self._fallback_providers
        for cb_idx, cb in self._circuit_breakers.items():
            base_name = type(all_providers[cb_idx]).__name__ if cb_idx < len(all_providers) else "unknown"
            dup_count = sum(
                1
                for other_idx in self._circuit_breakers
                if other_idx != cb_idx
                and other_idx < len(all_providers)
                and type(all_providers[other_idx]).__name__ == base_name
            )
            provider_name = f"{base_name}#{cb_idx}" if dup_count > 0 else base_name

            state = cb.state
            cb_states[provider_name] = state.value

            # 如果有熔断器处于 OPEN 状态，标记为降级
            if state == CircuitState.OPEN:
                degraded = True

        status = "healthy"
        if not self._started:
            status = "not_started"
        elif degraded:
            status = "degraded"

        return {
            "status": status,
            "name": self.name,
            "started": self._started,
            "middlewares_count": len(self._middlewares),
            "provider": type(self._provider).__name__,
            "fallback_providers": [type(p).__name__ for p in self._fallback_providers],
            "circuit_breakers": cb_states,
        }

    def health_check_sync(self) -> dict[str, Any]:
        """同步版本的健康检查方法。"""
        return self.health_check()


MiddlewareManager = Pipeline  # 向后兼容别名
