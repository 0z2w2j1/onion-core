"""Middleware latency benchmarks - measures pass-through overhead without LLM calls."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    SafetyGuardrailMiddleware,
)


@pytest.fixture
def echo_provider():
    return EchoProvider(reply="test")


@pytest.fixture
def context():
    return AgentContext(
        messages=[
            Message(role="user", content="Hello"),
        ]
    )


class TestMiddlewareLatency:
    """Benchmark middleware pass-through latency (no LLM call)."""

    def test_observability_middleware_latency(self, benchmark, context):
        async def run():
            mw = ObservabilityMiddleware()
            await mw.startup()
            try:
                return await mw.process_request(context)
            finally:
                await mw.shutdown()

        result = benchmark.pedantic(run, rounds=10000, iterations=1)
        assert result is not None

    def test_safety_middleware_latency(self, benchmark, context):
        async def run():
            mw = SafetyGuardrailMiddleware()
            await mw.startup()
            try:
                return await mw.process_request(context)
            finally:
                await mw.shutdown()

        result = benchmark.pedantic(run, rounds=10000, iterations=1)
        assert result is not None

    def test_context_window_middleware_latency(self, benchmark, context):
        async def run():
            mw = ContextWindowMiddleware(max_tokens=4000)
            await mw.startup()
            try:
                return await mw.process_request(context)
            finally:
                await mw.shutdown()

        result = benchmark.pedantic(run, rounds=10000, iterations=1)
        assert result is not None

    def test_rate_limit_middleware_latency(self, benchmark, context):
        async def run():
            mw = RateLimitMiddleware(window_seconds=60, max_requests=1000)
            await mw.startup()
            try:
                return await mw.process_request(context)
            finally:
                await mw.shutdown()

        result = benchmark.pedantic(run, rounds=10000, iterations=1)
        assert result is not None

    def test_pipeline_middleware_stack(self, benchmark, context, echo_provider):
        """Benchmark full middleware stack without Provider call."""
        pipeline = (
            Pipeline(provider=echo_provider)
            .add_middleware(ObservabilityMiddleware())
            .add_middleware(SafetyGuardrailMiddleware())
            .add_middleware(ContextWindowMiddleware(max_tokens=4000))
            .add_middleware(RateLimitMiddleware(window_seconds=60, max_requests=1000))
        )

        async def run():
            async with pipeline as p:
                ctx = await p._run_request(context)
                return ctx

        result = benchmark.pedantic(run, rounds=5000, iterations=1)
        assert result is not None


class TestPipelineThroughput:
    """Benchmark synchronous throughput."""

    def test_sync_throughput(self, benchmark, context):
        """Measure synchronous request throughput."""
        provider = EchoProvider(reply="test")
        pipeline = (
            Pipeline(provider=provider)
            .add_middleware(ObservabilityMiddleware())
            .add_middleware(SafetyGuardrailMiddleware())
        )

        async def run():
            async with pipeline:
                await provider.complete(context)

        result = benchmark.pedantic(run, rounds=1000, iterations=1)
        assert result is not None