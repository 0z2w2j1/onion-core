"""
Concurrency tests for thread safety and async correctness.

Tests:
- Multiple concurrent Pipeline.run() calls
- AgentRuntime cancel race conditions
- Lock contention (asyncio.Lock and threading.Lock)
- No deadlocks under high concurrency
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


class FastProvider:
    """Fast mock provider for concurrency tests."""
    
    def __init__(self):
        self.call_count = 0
        self.lock = threading.Lock()
    
    async def complete(self, context):
        with self.lock:
            self.call_count += 1
            call_num = self.call_count
        
        # Small delay to simulate real work
        await asyncio.sleep(0.001)
        
        return LLMResponse(
            content=f"Response {call_num}",
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
    
    async def stream(self, context):
        raise NotImplementedError("Stream not supported")
    
    async def cleanup(self):
        pass


@pytest.mark.asyncio
async def test_concurrent_pipeline_runs_no_race():
    """Test 50 concurrent pipeline runs don't cause race conditions."""
    provider = FastProvider()
    p = Pipeline(provider=provider, name="concurrent_test")
    
    await p.startup()
    try:
        # Create 50 concurrent requests
        num_requests = 50
        tasks = []
        
        for i in range(num_requests):
            context = AgentContext(
                request_id=f"req_{i}",
                messages=[Message(role="user", content=f"Message {i}")],
            )
            tasks.append(p.run(context))
        
        # Run all concurrently
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify all succeeded
        exceptions = [r for r in responses if isinstance(r, Exception)]
        if exceptions:
            raise exceptions[0]
        
        assert len(responses) == num_requests
        assert provider.call_count == num_requests
        
        # Verify all responses are unique
        contents = [r.content for r in responses]
        assert len(set(contents)) == num_requests
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_agent_runtime_immediate_cancel():
    """Test cancelling agent before it starts processing."""
    from onion_core.provider import LLMProvider
    
    started = asyncio.Event()
    cancelled = asyncio.Event()
    
    class BarrierProvider(LLMProvider):
        async def complete(self, context):
            started.set()
            await cancelled.wait()  # Block until cancel is verified
            return LLMResponse(content="done", finish_reason=FinishReason.STOP)
        
        async def stream(self, context):
            raise NotImplementedError
    
        async def cleanup(self):
            pass
    
    provider = BarrierProvider()
    registry = ToolRegistry()
    config = AgentConfig(model="test", max_steps=10)
    
    agent = AgentRuntime(
        config=config,
        llm_provider=provider,
        tool_registry=registry,
    )
    
    task = asyncio.create_task(agent.run(user_message="Test"))
    await started.wait()
    agent.cancel()
    cancelled.set()
    
    state = await asyncio.wait_for(task, timeout=2.0)
    
    assert state.status == AgentStatus.CANCELLED


@pytest.mark.asyncio
async def test_multiple_agents_concurrent_execution():
    """Test multiple AgentRuntime instances running concurrently."""
    from onion_core.provider import LLMProvider
    
    class CountingProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.lock = threading.Lock()
        
        async def complete(self, context):
            with self.lock:
                self.call_count += 1
                num = self.call_count
            
            await asyncio.sleep(0.01)
            
            return LLMResponse(
                content=f"Agent response {num}",
                finish_reason=FinishReason.STOP,
                usage=UsageStats(),
            )
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = CountingProvider()
    registry = ToolRegistry()
    config = AgentConfig(model="test", max_steps=2)
    
    # Create 5 agents
    num_agents = 5
    agents = [
        AgentRuntime(config=config, llm_provider=provider, tool_registry=registry)
        for _ in range(num_agents)
    ]
    
    # Run all concurrently
    tasks = [agent.run(user_message=f"Query {i}") for i, agent in enumerate(agents)]
    states = await asyncio.gather(*tasks)
    
    # Verify all completed
    assert len(states) == num_agents
    assert all(s.status in [AgentStatus.FINISHED, AgentStatus.CANCELLED] for s in states)
    
    # Verify provider was called
    assert provider.call_count >= num_agents


@pytest.mark.asyncio
async def test_lock_contention_no_deadlock():
    """Test that locks don't cause deadlocks under contention."""
    from onion_core.provider import LLMProvider
    
    class LockTestingProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.thread_lock = threading.Lock()
        
        async def complete(self, context):
            # Simulate work with lock - keep lock scope minimal to avoid deadlock
            with self.thread_lock:
                self.call_count += 1
            
            # Async operation outside the lock
            await asyncio.sleep(0.001)
            
            return LLMResponse(
                content="OK",
                finish_reason=FinishReason.STOP,
                usage=UsageStats(),
            )
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = LockTestingProvider()
    p = Pipeline(provider=provider, name="lock_test")
    
    await p.startup()
    try:
        # High concurrency to stress test locks
        num_requests = 100
        tasks = []
        
        for i in range(num_requests):
            context = AgentContext(
                request_id=f"lock_req_{i}",
                messages=[Message(role="user", content="Test")],
            )
            tasks.append(p.run(context))
        
        # Should complete without deadlock (with timeout as safety)
        responses = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=10.0
        )
        
        # Check for exceptions
        exceptions = [r for r in responses if isinstance(r, Exception)]
        if exceptions:
            raise exceptions[0]
        
        assert len(responses) == num_requests
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_asyncio_lock_vs_threading_lock():
    """Test interaction between asyncio.Lock and threading.Lock."""
    from onion_core.provider import LLMProvider
    
    class MixedLockProvider(LLMProvider):
        def __init__(self):
            self.async_lock = asyncio.Lock()
            self.thread_lock = threading.Lock()
            self.count = 0
        
        async def complete(self, context):
            # Use both types of locks - minimize thread lock hold time
            async with self.async_lock:
                with self.thread_lock:
                    self.count += 1
                    count_val = self.count
                
                # Thread lock released, now do async work
                await asyncio.sleep(0.001)
            
            return LLMResponse(
                content=f"Count: {count_val}",
                finish_reason=FinishReason.STOP,
                usage=UsageStats(),
            )
        
        async def stream(self, context):
            raise NotImplementedError("Stream not supported")
        
        async def cleanup(self):
            pass
    
    provider = MixedLockProvider()
    p = Pipeline(provider=provider, name="mixed_lock_test")
    
    await p.startup()
    try:
        num_requests = 20
        tasks = [
            p.run(AgentContext(
                request_id=f"mixed_{i}",
                messages=[Message(role="user", content="Test")],
            ))
            for i in range(num_requests)
        ]
        
        responses = await asyncio.gather(*tasks)
        
        assert len(responses) == num_requests
        assert provider.count == num_requests
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_concurrent_cancel_and_run():
    """Test cancel() called while run() is executing."""
    from onion_core.provider import LLMProvider

    llm_started = asyncio.Event()
    proceed = asyncio.Event()

    class CancellableProvider(LLMProvider):
        async def complete(self, context):
            llm_started.set()
            await proceed.wait()
            return LLMResponse(content="Response", finish_reason=FinishReason.STOP, usage=UsageStats())

        async def stream(self, context):
            raise NotImplementedError

        async def cleanup(self):
            pass

    provider = CancellableProvider()
    registry = ToolRegistry()
    config = AgentConfig(model="test", max_steps=5)

    agent = AgentRuntime(config=config, llm_provider=provider, tool_registry=registry)

    task = asyncio.create_task(agent.run(user_message="Test"))
    await llm_started.wait()
    agent.cancel()
    proceed.set()

    state = await asyncio.wait_for(task, timeout=2.0)

    assert state.status == AgentStatus.CANCELLED


@pytest.mark.asyncio
async def test_high_concurrency_stress_test():
    """Stress test with 200 concurrent requests."""
    provider = FastProvider()
    p = Pipeline(provider=provider, name="stress_test")
    
    await p.startup()
    try:
        num_requests = 200
        tasks = []
        
        for i in range(num_requests):
            context = AgentContext(
                request_id=f"stress_{i}",
                messages=[Message(role="user", content=f"Msg {i}")],
            )
            tasks.append(p.run(context))
        
        # Run with timeout to detect hangs
        responses = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=30.0
        )
        
        # Count successes and failures
        successes = [r for r in responses if not isinstance(r, Exception)]
        exceptions = [r for r in responses if isinstance(r, Exception)]
        
        # All should succeed
        assert len(successes) == num_requests
        assert len(exceptions) == 0
        assert provider.call_count == num_requests
    finally:
        await p.shutdown()
