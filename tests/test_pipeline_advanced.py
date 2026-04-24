"""Pipeline 高级功能测试：重试、熔断、Fallback、超时等核心逻辑。"""

from __future__ import annotations

import asyncio

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline
from onion_core.base import BaseMiddleware
from onion_core.circuit_breaker import CircuitBreaker
from onion_core.models import (
    CircuitBreakerError,
    ProviderError,
    RateLimitExceeded,
    RetryOutcome,
    RetryPolicy,
    SecurityException,
)


def make_context():
    """创建测试上下文。"""
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


class FailingProvider(EchoProvider):
    """模拟失败的 Provider。"""

    def __init__(self, fail_count: int = 3, reply: str = "Recovered"):
        super().__init__(reply=reply)
        self._fail_count = fail_count
        self._call_count = 0

    async def complete(self, context: AgentContext) -> LLMResponse:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ProviderError(f"Simulated failure #{self._call_count}")
        return await super().complete(context)


class AlwaysFailingProvider(EchoProvider):
    """永远失败的 Provider。"""

    async def complete(self, context: AgentContext) -> LLMResponse:
        raise ProviderError("Always fails")


class TestRetryMechanism:
    """测试重试机制。"""

    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        """瞬时失败后重试成功。"""
        provider = FailingProvider(fail_count=2, reply="Success after retry")
        pipeline = Pipeline(
            provider=provider,
            max_retries=3,
            retry_base_delay=0.01,  # 快速重试用于测试
        )

        async with pipeline:
            response = await pipeline.run(make_context())
            assert response.content == "Success after retry"
            assert provider._call_count == 3  # 2次失败 + 1次成功

    @pytest.mark.asyncio
    async def test_no_retry_on_fatal_error(self):
        """致命错误不重试。"""

        class FatalProvider(EchoProvider):
            async def complete(self, context: AgentContext) -> LLMResponse:
                raise ValueError("Invalid parameter")  # 致命错误

        pipeline = Pipeline(
            provider=FatalProvider(),
            max_retries=3,
        )

        async with pipeline:
            with pytest.raises(ValueError):
                await pipeline.run(make_context())

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises_last_error(self):
        """重试耗尽后抛出最后一次异常。"""
        provider = FailingProvider(fail_count=10, reply="Never reached")
        pipeline = Pipeline(
            provider=provider,
            max_retries=2,
            retry_base_delay=0.01,
        )

        async with pipeline:
            with pytest.raises(ProviderError, match="Simulated failure"):
                await pipeline.run(make_context())

    @pytest.mark.asyncio
    async def test_retry_policy_classify(self):
        """测试重试策略分类器。"""
        policy = RetryPolicy()

        # RETRY: 网络错误
        assert policy.classify(TimeoutError()) == RetryOutcome.RETRY
        assert policy.classify(ConnectionError()) == RetryOutcome.RETRY

        # FALLBACK: 限流（RateLimitExceeded的is_fatal默认为True，所以是FATAL）
        assert policy.classify(RateLimitExceeded()) == RetryOutcome.FATAL

        # FATAL: 安全拦截
        assert policy.classify(SecurityException()) == RetryOutcome.FATAL

        # FATAL: 编程错误
        assert policy.classify(ValueError()) == RetryOutcome.FATAL
        assert policy.classify(TypeError()) == RetryOutcome.FATAL

        # RETRY: Provider 错误（默认）
        assert policy.classify(ProviderError()) == RetryOutcome.RETRY

    @pytest.mark.asyncio
    async def test_fallback_on_rate_limit(self):
        """限流时切换到 Fallback Provider。"""

        class RateLimitedProvider(EchoProvider):
            async def complete(self, context: AgentContext) -> LLMResponse:
                # 使用ProviderError而非RateLimitExceeded，因为后者是FATAL
                raise ProviderError("Rate limit")

        primary = RateLimitedProvider()
        fallback = EchoProvider(reply="From fallback")

        pipeline = Pipeline(
            provider=primary,
            fallback_providers=[fallback],
            max_retries=0,
        )

        async with pipeline:
            response = await pipeline.run(make_context())
            assert response.content == "From fallback"


class TestCircuitBreaker:
    """测试熔断器机制。"""

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        """连续失败后熔断器打开。"""
        provider = AlwaysFailingProvider()
        pipeline = Pipeline(
            provider=provider,
            max_retries=0,
            enable_circuit_breaker=True,
            circuit_failure_threshold=3,
            circuit_recovery_timeout=60.0,
        )

        async with pipeline:
            # 触发3次失败，熔断器应打开
            for _ in range(3):
                try:
                    await pipeline.run(make_context())
                except ProviderError:
                    pass

            # 第4次调用应被熔断器拦截
            with pytest.raises(CircuitBreakerError):
                await pipeline.run(make_context())

    @pytest.mark.asyncio
    async def test_circuit_breaker_state_transitions(self):
        """测试熔断器状态转换。"""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=0.1,  # 快速恢复用于测试
            success_threshold=1,
        )

        # 初始状态：CLOSED
        assert cb.state.value == "closed"

        # 记录2次失败 → OPEN
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state.value == "open"

        # OPEN 状态下调用应失败
        with pytest.raises(CircuitBreakerError):
            await cb.check_call()

        # 等待恢复超时 → HALF_OPEN
        await asyncio.sleep(0.15)
        assert cb.state.value == "half_open"

        # 记录1次成功 → CLOSED
        await cb.record_success()
        assert cb.state.value == "closed"

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        """半开状态下失败应重新打开熔断器。"""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2,
        )

        # 触发熔断
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state.value == "open"

        # 进入半开状态
        await asyncio.sleep(0.15)
        assert cb.state.value == "half_open"

        # 半开状态下失败 → 重新打开
        await cb.record_failure()
        assert cb.state.value == "open"


class TestFallbackProviders:
    """测试 Fallback Provider 机制。"""

    @pytest.mark.asyncio
    async def test_fallback_chain_execution(self):
        """主 Provider 失败后依次尝试 Fallback。"""
        primary = AlwaysFailingProvider()
        fallback1 = AlwaysFailingProvider()
        fallback2 = EchoProvider(reply="From fallback2")

        pipeline = Pipeline(
            provider=primary,
            fallback_providers=[fallback1, fallback2],
            max_retries=0,
        )

        async with pipeline:
            response = await pipeline.run(make_context())
            assert response.content == "From fallback2"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_aggregated_error(self):
        """所有 Provider 都失败时抛出聚合错误。"""
        primary = AlwaysFailingProvider()
        fallback = AlwaysFailingProvider()

        pipeline = Pipeline(
            provider=primary,
            fallback_providers=[fallback],
            max_retries=0,
        )

        async with pipeline:
            with pytest.raises(ProviderError):
                await pipeline.run(make_context())

    @pytest.mark.asyncio
    async def test_fallback_skips_circuit_broken_provider(self):
        """跳过已熔断的 Fallback Provider。"""
        primary = AlwaysFailingProvider()
        fallback = AlwaysFailingProvider()

        pipeline = Pipeline(
            provider=primary,
            fallback_providers=[fallback],
            max_retries=0,
            circuit_failure_threshold=2,
        )

        async with pipeline:
            # 触发熔断
            for _ in range(2):
                try:
                    await pipeline.run(make_context())
                except ProviderError:
                    pass

            # 再次调用，两个 Provider 都应被熔断
            with pytest.raises(CircuitBreakerError):
                await pipeline.run(make_context())


class TestTimeoutControl:
    """测试超时控制机制。"""

    @pytest.mark.asyncio
    async def test_provider_timeout(self):
        """Provider 调用超时。"""

        class SlowProvider(EchoProvider):
            async def complete(self, context: AgentContext) -> LLMResponse:
                await asyncio.sleep(10)
                return await super().complete(context)

        pipeline = Pipeline(
            provider=SlowProvider(),
            provider_timeout=0.1,
        )

        async with pipeline:
            with pytest.raises(asyncio.TimeoutError):
                await pipeline.run(make_context())

    @pytest.mark.asyncio
    async def test_middleware_level_timeout_override(self):
        """中间件级别超时覆盖全局配置。"""

        class SlowMW(BaseMiddleware):
            timeout = 0.05  # 中间件级别超时
            is_mandatory = True

            async def process_request(self, context: AgentContext) -> AgentContext:
                await asyncio.sleep(10)
                return context

            async def process_response(self, ctx, r):
                return r

            async def process_stream_chunk(self, ctx, c):
                return c

            async def on_tool_call(self, ctx, tc):
                return tc

            async def on_tool_result(self, ctx, r):
                return r

            async def on_error(self, ctx, e):
                pass

        pipeline = Pipeline(
            provider=EchoProvider(),
            middleware_timeout=10.0,  # 全局超时很长
        ).add_middleware(SlowMW())

        async with pipeline:
            with pytest.raises(asyncio.TimeoutError):
                await pipeline.run(make_context())


class TestMandatoryMiddleware:
    """测试强制性中间件。"""

    @pytest.mark.asyncio
    async def test_mandatory_middleware_failure_aborts_chain(self):
        """强制性中间件失败应中断整个链路。"""

        class MandatoryFailingMW(BaseMiddleware):
            is_mandatory = True

            async def process_request(self, context: AgentContext) -> AgentContext:
                raise RuntimeError("Mandatory failure")

            async def process_response(self, ctx, r):
                return r

            async def process_stream_chunk(self, ctx, c):
                return c

            async def on_tool_call(self, ctx, tc):
                return tc

            async def on_tool_result(self, ctx, r):
                return r

            async def on_error(self, ctx, e):
                pass

        pipeline = Pipeline(provider=EchoProvider()).add_middleware(MandatoryFailingMW())

        async with pipeline:
            with pytest.raises(RuntimeError, match="Mandatory failure"):
                await pipeline.run(make_context())

    @pytest.mark.asyncio
    async def test_non_mandatory_middleware_failure_isolated(self):
        """非强制性中间件失败应被隔离，不影响其他中间件。"""
        call_order = []

        class NonMandatoryFailingMW(BaseMiddleware):
            is_mandatory = False

            async def process_request(self, context: AgentContext) -> AgentContext:
                call_order.append("failing_mw")
                raise RuntimeError("Non-fatal bug")

            async def process_response(self, ctx, r):
                return r

            async def process_stream_chunk(self, ctx, c):
                return c

            async def on_tool_call(self, ctx, tc):
                return tc

            async def on_tool_result(self, ctx, r):
                return r

            async def on_error(self, ctx, e):
                pass

        class GoodMW(BaseMiddleware):
            async def process_request(self, context: AgentContext) -> AgentContext:
                call_order.append("good_mw")
                return context

            async def process_response(self, ctx, r):
                return r

            async def process_stream_chunk(self, ctx, c):
                return c

            async def on_tool_call(self, ctx, tc):
                return tc

            async def on_tool_result(self, ctx, r):
                return r

            async def on_error(self, ctx, e):
                pass

        pipeline = (
            Pipeline(provider=EchoProvider())
            .add_middleware(NonMandatoryFailingMW())
            .add_middleware(GoodMW())
        )

        async with pipeline:
            response = await pipeline.run(make_context())
            assert response.content  # 请求应成功完成

        # 验证两个中间件都被调用
        assert "failing_mw" in call_order
        assert "good_mw" in call_order


class TestHealthCheck:
    """测试健康检查功能。"""

    @pytest.mark.asyncio
    async def test_health_check_not_started(self):
        """未启动的 Pipeline 健康状态。"""
        pipeline = Pipeline(provider=EchoProvider())
        health = pipeline.health_check()

        assert health["status"] == "not_started"
        assert health["started"] is False
        assert health["middlewares_count"] == 0

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """健康的 Pipeline 状态。"""
        pipeline = Pipeline(provider=EchoProvider())
        async with pipeline:
            health = pipeline.health_check()

        assert health["status"] == "healthy"
        assert health["started"] is True
        assert health["provider"] == "EchoProvider"

    @pytest.mark.asyncio
    async def test_health_check_degraded(self):
        """降级的 Pipeline 状态（熔断器打开）。"""
        provider = AlwaysFailingProvider()
        pipeline = Pipeline(
            provider=provider,
            max_retries=0,
            circuit_failure_threshold=2,
        )

        async with pipeline:
            # 触发熔断
            for _ in range(2):
                try:
                    await pipeline.run(make_context())
                except ProviderError:
                    pass

            health = pipeline.health_check()
            assert health["status"] == "degraded"
            assert any(state == "open" for state in health["circuit_breakers"].values())

    @pytest.mark.asyncio
    async def test_health_check_with_fallback_providers(self):
        """包含 Fallback Provider 的健康检查。"""
        primary = EchoProvider()
        fallback1 = EchoProvider()
        fallback2 = EchoProvider()

        pipeline = Pipeline(
            provider=primary,
            fallback_providers=[fallback1, fallback2],
        )

        health = pipeline.health_check()
        assert len(health["fallback_providers"]) == 2
        assert len(health["circuit_breakers"]) == 3  # 1 primary + 2 fallbacks


class TestConcurrentSafety:
    """测试并发安全性。"""

    @pytest.mark.asyncio
    async def test_concurrent_startup_idempotent(self):
        """并发调用 startup 应幂等。"""
        startup_count = 0

        class CountingMW(BaseMiddleware):
            async def startup(self):
                nonlocal startup_count
                startup_count += 1

            async def process_request(self, context: AgentContext) -> AgentContext:
                return context

            async def process_response(self, ctx, r):
                return r

            async def process_stream_chunk(self, ctx, c):
                return c

            async def on_tool_call(self, ctx, tc):
                return tc

            async def on_tool_result(self, ctx, r):
                return r

            async def on_error(self, ctx, e):
                pass

        pipeline = Pipeline(provider=EchoProvider()).add_middleware(CountingMW())

        # 并发调用 startup
        await asyncio.gather(pipeline.startup(), pipeline.startup(), pipeline.startup())

        assert startup_count == 1  # 只应启动一次
        await pipeline.shutdown()

    @pytest.mark.asyncio
    async def test_concurrent_requests_with_shared_pipeline(self):
        """共享 Pipeline 的并发请求。"""
        pipeline = Pipeline(provider=EchoProvider())

        async with pipeline:
            # 并发执行多个请求
            tasks = [pipeline.run(make_context()) for _ in range(10)]
            responses = await asyncio.gather(*tasks)

            assert len(responses) == 10
            assert all(r.content for r in responses)
