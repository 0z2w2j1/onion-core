"""Tests for Pipeline health check functionality."""

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import ObservabilityMiddleware


class TestPipelineHealthCheck:
    """Test suite for Pipeline.health_check() method."""

    def test_health_check_not_started(self):
        """Test health check before pipeline startup."""
        p = Pipeline(provider=EchoProvider(), name="test-pipeline")
        health = p.health_check()

        assert health["status"] == "not_started"
        assert health["name"] == "test-pipeline"
        assert health["started"] is False
        assert health["middlewares_count"] == 0
        assert health["provider"] == "EchoProvider"
        assert health["fallback_providers"] == []
        assert health["circuit_breakers"] == {"EchoProvider": "closed"}

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Test health check after successful startup."""
        async with Pipeline(
            provider=EchoProvider(), name="healthy-pipeline"
        ) as p:
            p.add_middleware(ObservabilityMiddleware())
            health = p.health_check()

            assert health["status"] == "healthy"
            assert health["started"] is True
            assert health["middlewares_count"] == 1
            assert health["circuit_breakers"]["EchoProvider"] == "closed"

    @pytest.mark.asyncio
    async def test_health_check_with_fallback_providers(self):
        """Test health check with fallback providers configured."""
        primary = EchoProvider(reply="primary")
        fallback1 = EchoProvider(reply="fallback1")
        fallback2 = EchoProvider(reply="fallback2")

        async with Pipeline(
            provider=primary,
            fallback_providers=[fallback1, fallback2],
            name="multi-provider",
        ) as p:
            health = p.health_check()

            assert health["status"] == "healthy"
            assert health["provider"] == "EchoProvider"
            assert len(health["fallback_providers"]) == 2
            assert "EchoProvider" in health["fallback_providers"]
            # Should have 3 circuit breakers (1 primary + 2 fallbacks)
            assert len(health["circuit_breakers"]) == 3

    def test_health_check_sync_method(self):
        """Test synchronous version of health check."""
        p = Pipeline(provider=EchoProvider(), name="sync-test")
        health = p.health_check_sync()

        assert health["status"] == "not_started"
        assert health["name"] == "sync-test"

    @pytest.mark.asyncio
    async def test_health_check_circuit_breaker_states(self):
        """Test that health check reports circuit breaker states correctly."""
        from unittest.mock import AsyncMock, patch

        from onion_core.models import CircuitState

        async with Pipeline(
            provider=EchoProvider(), name="cb-test"
        ) as p:
            # Manually trip a circuit breaker for testing
            cb = list(p._circuit_breakers.values())[0]
            cb._state = CircuitState.OPEN
            cb._last_failure_time = 0  # Force OPEN state

            health = p.health_check()

            # Should be degraded because circuit breaker is OPEN
            assert health["status"] == "degraded"
            assert any(
                state == "open" for state in health["circuit_breakers"].values()
            )

    @pytest.mark.asyncio
    async def test_health_check_after_run(self):
        """Test health check after running a request."""
        async with Pipeline(
            provider=EchoProvider(), name="after-run"
        ) as p:
            p.add_middleware(ObservabilityMiddleware())

            # Run a request
            ctx = AgentContext(messages=[Message(role="user", content="Hello")])
            response = await p.run(ctx)

            assert response.content is not None

            # Check health after run
            health = p.health_check()
            assert health["status"] == "healthy"
            assert health["started"] is True
            assert health["middlewares_count"] == 1
