"""Benchmark fixtures."""

from __future__ import annotations

import pytest
import pytest_asyncio

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    SafetyGuardrailMiddleware,
)


@pytest.fixture
def echo_provider():
    return EchoProvider(reply="Hello from echo.")


@pytest.fixture
def empty_context():
    return AgentContext(
        messages=[
            Message(role="user", content="test"),
        ]
    )


@pytest.fixture
def simple_pipeline(echo_provider):
    return (
        Pipeline(provider=echo_provider)
        .add_middleware(ObservabilityMiddleware())
        .add_middleware(SafetyGuardrailMiddleware())
        .add_middleware(ContextWindowMiddleware(max_tokens=4000))
    )


@pytest.fixture
def full_pipeline(echo_provider):
    return (
        Pipeline(provider=echo_provider)
        .add_middleware(ObservabilityMiddleware())
        .add_middleware(RateLimitMiddleware(window_seconds=60, max_requests=1000))
        .add_middleware(SafetyGuardrailMiddleware())
        .add_middleware(ContextWindowMiddleware(max_tokens=4000))
    )


@pytest_asyncio.fixture
async def started_pipeline(simple_pipeline):
    async with simple_pipeline:
        yield simple_pipeline


@pytest_asyncio.fixture
async def started_full_pipeline(full_pipeline):
    async with full_pipeline:
        yield full_pipeline