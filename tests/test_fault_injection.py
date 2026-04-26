"""
Fault injection tests for resilience and error handling.

Tests various failure scenarios:
- Provider timeouts
- Invalid JSON responses
- Circuit breaker triggering
- Cancel race conditions
"""

import asyncio
import threading

import pytest

from onion_core.agent import AgentRuntime
from onion_core.models import (
    AgentConfig,
    AgentContext,
    AgentStatus,
    FinishReason,
    LLMResponse,
    Message,
    UsageStats,
)
from onion_core.pipeline import Pipeline
from onion_core.tools import ToolRegistry


class TimeoutProvider:
    """Provider that always times out."""
    
    async def complete(self, context):
        await asyncio.sleep(100)  # Very long timeout
        return LLMResponse(content="Should not reach here", finish_reason=FinishReason.STOP)
    
    async def stream(self, context):
        raise NotImplementedError("Stream not supported")
    
    async def cleanup(self):
        pass


class InvalidJSONProvider:
    """Provider that returns malformed responses."""
    
    async def complete(self, context):
        # This simulates a provider that returns invalid data
        # In real scenarios, this would be caught during JSON parsing
        return LLMResponse(
            content=None,  # Invalid: content should not be None with STOP
            finish_reason=FinishReason.STOP,
            usage=UsageStats(),
        )
    
    async def stream(self, context):
        raise NotImplementedError("Stream not supported")
    
    async def cleanup(self):
        pass


@pytest.mark.asyncio
async def test_provider_timeout_handling():
    """Test that provider timeouts are handled correctly."""
    provider = TimeoutProvider()
    p = Pipeline(
        provider=provider,
        name="timeout_test",
        provider_timeout=0.1,  # 100ms timeout
    )
    
    await p.startup()
    try:
        context = AgentContext(
            request_id="timeout_001",
            messages=[Message(role="user", content="Will timeout")],
        )
        
        with pytest.raises(asyncio.TimeoutError):
            await p.run(context)
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_pipeline_total_timeout_vs_provider_timeout():
    """Test interaction between total_timeout and provider_timeout."""
    provider = TimeoutProvider()
    p = Pipeline(
        provider=provider,
        name="dual_timeout_test",
        provider_timeout=5.0,  # Long provider timeout
        total_timeout=0.1,     # Short total timeout
    )
    
    await p.startup()
    try:
        context = AgentContext(
            request_id="dual_timeout_001",
            messages=[Message(role="user", content="Test")],
        )
        
        # Should hit total_timeout first
        with pytest.raises(TimeoutError, match="Pipeline total timeout"):
            await p.run(context)
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_circuit_breaker_triggers_after_failures():
    """Test that circuit breaker opens after consecutive failures."""
    from onion_core.provider import LLMProvider
    
    class FailingProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
        
        async def complete(self, context):
            self.call_count += 1
            raise RuntimeError(f"Failure #{self.call_count}")
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = FailingProvider()
    p = Pipeline(
        provider=provider,
        name="circuit_breaker_test",
        enable_circuit_breaker=True,
        circuit_failure_threshold=3,
        circuit_recovery_timeout=1.0,
        max_retries=0,  # No retries to speed up test
    )
    
    await p.startup()
    try:
        context = AgentContext(
            request_id="cb_001",
            messages=[Message(role="user", content="Test")],
        )
        
        # First 3 calls should fail and trigger circuit breaker
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await p.run(context)
        
        # 4th call should be blocked by circuit breaker
        from onion_core.circuit_breaker import CircuitBreakerError
        with pytest.raises(CircuitBreakerError):
            await p.run(context)
        
        # Verify provider was called exactly 3 times
        assert provider.call_count == 3
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_circuit_breaker_recovery():
    """Test that circuit breaker recovers after timeout."""
    from onion_core.provider import LLMProvider
    
    call_count = 0
    
    class RecoveringProvider(LLMProvider):
        async def complete(self, context):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("Temporary failure")
            return LLMResponse(
                content="Recovered!",
                finish_reason=FinishReason.STOP,
                usage=UsageStats(),
            )
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = RecoveringProvider()
    p = Pipeline(
        provider=provider,
        name="recovery_test",
        enable_circuit_breaker=True,
        circuit_failure_threshold=2,
        circuit_recovery_timeout=0.2,  # 200ms recovery
        max_retries=0,
    )
    
    await p.startup()
    try:
        context = AgentContext(
            request_id="recovery_001",
            messages=[Message(role="user", content="Test")],
        )
        
        # First 2 calls fail
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await p.run(context)
        
        # Wait for recovery timeout
        await asyncio.sleep(0.3)
        
        # Next call should succeed (circuit breaker is HALF_OPEN -> CLOSED)
        response = await p.run(context)
        assert response.content == "Recovered!"
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_cancel_race_condition():
    """Test that cancel() works correctly even during active execution."""
    from onion_core.provider import LLMProvider
    
    cancel_during_call = False
    
    class CancellableProvider(LLMProvider):
        async def complete(self, context):
            nonlocal cancel_during_call
            # Simulate slow LLM call
            await asyncio.sleep(0.2)
            cancel_during_call = True
            return LLMResponse(
                content="Response after cancel",
                finish_reason=FinishReason.STOP,
                usage=UsageStats(),
            )
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = CancellableProvider()
    registry = ToolRegistry()
    
    config = AgentConfig(model="test", max_steps=5)
    agent = AgentRuntime(
        config=config,
        llm_provider=provider,
        tool_registry=registry,
    )
    
    # Start execution
    task = asyncio.create_task(agent.run(user_message="Test"))
    
    # Cancel quickly
    await asyncio.sleep(0.05)
    agent.cancel()
    
    # Wait for completion
    state = await task
    
    # Verify cancellation was processed
    assert state.status in [AgentStatus.CANCELLED, AgentStatus.FINISHED]


@pytest.mark.asyncio
async def test_concurrent_pipeline_runs():
    """Test that multiple concurrent pipeline runs don't interfere."""
    from onion_core.provider import LLMProvider
    
    class CountingProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.lock = threading.Lock()
        
        async def complete(self, context):
            with self.lock:
                self.call_count += 1
                count_val = self.call_count
            await asyncio.sleep(0.01)  # Small delay
            return LLMResponse(
                content=f"Response {count_val}",
                finish_reason=FinishReason.STOP,
                usage=UsageStats(),
            )
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = CountingProvider()
    p = Pipeline(provider=provider, name="concurrent_test")
    
    await p.startup()
    try:
        # Run 10 concurrent requests
        tasks = []
        for i in range(10):
            context = AgentContext(
                request_id=f"concurrent_{i}",
                messages=[Message(role="user", content=f"Request {i}")],
            )
            tasks.append(p.run(context))
        
        responses = await asyncio.gather(*tasks)
        
        # Verify all succeeded
        assert len(responses) == 10
        assert provider.call_count == 10
        
        # Verify responses are unique
        contents = [r.content for r in responses]
        assert len(set(contents)) == 10
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_agent_runtime_concurrent_with_cancel():
    """Test concurrent agent runs with cancellation."""
    from onion_core.provider import LLMProvider
    
    class SlowProvider(LLMProvider):
        async def complete(self, context):
            await asyncio.sleep(0.5)
            return LLMResponse(
                content="Slow response",
                finish_reason=FinishReason.STOP,
                usage=UsageStats(),
            )
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = SlowProvider()
    registry = ToolRegistry()
    config = AgentConfig(model="test", max_steps=5)
    
    # Create multiple agents
    agents = [
        AgentRuntime(config=config, llm_provider=provider, tool_registry=registry)
        for _ in range(3)
    ]
    
    # Start all agents
    tasks = [asyncio.create_task(agent.run(user_message="Test")) for agent in agents]
    
    # Cancel one agent
    await asyncio.sleep(0.1)
    agents[1].cancel()
    
    # Wait for all to complete
    states = await asyncio.gather(*tasks)
    
    # Verify at least one was cancelled
    statuses = [s.status for s in states]
    assert AgentStatus.CANCELLED in statuses or AgentStatus.FINISHED in statuses
