"""Additional tests for Pipeline fallback and retry logic."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import ObservabilityMiddleware


@pytest.fixture
def context():
    return AgentContext(
        messages=[
            Message(role="user", content="test"),
        ]
    )


class TestPipelineFallback:
    """Test Pipeline fallback providers."""

    @pytest.mark.asyncio
    async def test_fallback_provider_triggered(self, context):
        class FailingProvider:
            async def complete(self, ctx):
                raise RuntimeError("primary failed")

        class SuccessProvider:
            async def complete(self, ctx):
                from onion_core.models import LLMResponse
                return LLMResponse(content="fallback response")

        pipeline = Pipeline(
            provider=FailingProvider(),
            fallback_providers=[SuccessProvider()],
        )
        pipeline.add_middleware(ObservabilityMiddleware())

        async with pipeline:
            result = await pipeline.run(context)
            assert result.content == "fallback response"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self, context):
        class FailingProvider:
            async def complete(self, ctx):
                raise RuntimeError("failed")

        pipeline = Pipeline(
            provider=FailingProvider(),
            fallback_providers=[FailingProvider()],
            max_retries=0,
        )

        async with pipeline:
            with pytest.raises(RuntimeError):
                await pipeline.run(context)


class TestPipelineCircuitBreaker:
    """Test Pipeline circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_enabled_by_default(self):
        provider = EchoProvider(reply="test")
        pipeline = Pipeline(provider=provider)
        assert pipeline._enable_circuit_breaker

    @pytest.mark.asyncio
    async def test_circuit_breaker_disabled(self):
        provider = EchoProvider(reply="test")
        pipeline = Pipeline(provider=provider, enable_circuit_breaker=False)
        assert not pipeline._enable_circuit_breaker


class TestPipelineRetryDetails:
    """More detailed retry tests."""

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self, context):
        from onion_core.models import LLMResponse

        class SlowFailingProvider:
            call_count = 0

            async def complete(self, ctx):
                SlowFailingProvider.call_count += 1
                if SlowFailingProvider.call_count < 3:
                    raise RuntimeError("temporary failure")
                return LLMResponse(content="success after retry")

        provider = SlowFailingProvider()
        pipeline = Pipeline(provider=provider, max_retries=3, retry_base_delay=0.01)
        pipeline.add_middleware(ObservabilityMiddleware())

        async with pipeline:
            result = await pipeline.run(context)
            assert SlowFailingProvider.call_count == 3
            assert result.content == "success after retry"


class TestPipelineEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_empty_middleware_list(self, context):
        provider = EchoProvider(reply="test")
        pipeline = Pipeline(provider=provider)

        async with pipeline:
            result = await pipeline.run(context)
            assert result.content == "test"

    @pytest.mark.asyncio
    async def test_stream_with_empty_messages(self):
        context = AgentContext(messages=[])

        provider = EchoProvider(reply="test")
        pipeline = Pipeline(provider=provider)
        pipeline.add_middleware(ObservabilityMiddleware())

        async with pipeline:
            result = await pipeline.run(context)
            assert result.content == "test"

    @pytest.mark.asyncio
    async def test_provider_with_timeout(self, context):
        provider = EchoProvider(reply="test")
        pipeline = Pipeline(provider=provider, provider_timeout=5.0)

        async with pipeline:
            result = await pipeline.run(context)
            assert result.content == "test"