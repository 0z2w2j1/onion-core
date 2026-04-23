"""Tests for base middleware and Provider integration."""

from __future__ import annotations

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.base import BaseMiddleware
from onion_core.middlewares import ObservabilityMiddleware
from onion_core.provider import LLMProvider


class TestProvider:
    """Test LLMProvider abstract class."""

    def test_provider_attribute(self):
        class TestProvider(LLMProvider):
            async def complete(self, ctx): pass
            def stream(self, ctx): pass

        provider = TestProvider()
        assert hasattr(provider, 'complete')
        assert hasattr(provider, 'stream')


class TestMiddlewareInheritance:
    """Test concrete middleware inheritance."""

    @pytest.mark.asyncio
    async def test_middleware_integration(self):
        context = AgentContext(messages=[Message(role="user", content="test")])
        provider = EchoProvider(reply="success")
        pipeline = Pipeline(provider=provider)
        pipeline.add_middleware(ObservabilityMiddleware())

        async with pipeline:
            result = await pipeline.run(context)
            assert result.content == "success"