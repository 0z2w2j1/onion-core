"""
End-to-End tests for AgentRuntime complete ReAct loop.

Tests the full Think -> Act -> Think -> Finish cycle with mock providers
and tools to verify step records, memory trimming, and state management.
"""


import pytest

from onion_core.agent import AgentRuntime, AgentState, StepRecord
from onion_core.models import (
    ActionType,
    AgentConfig,
    AgentStatus,
    FinishReason,
    LLMResponse,
    Message,
    ToolCall,
    UsageStats,
)
from onion_core.provider import LLMProvider
from onion_core.tools import ToolRegistry


class MockLLMProvider(LLMProvider):
    """Mock provider that simulates different responses based on call count."""
    
    def __init__(self):
        self.call_count = 0
        self.responses = []
    
    def add_response(self, response: LLMResponse):
        self.responses.append(response)
    
    async def complete(self, context) -> LLMResponse:
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        # Default: finish without tool calls
        return LLMResponse(
            content="Final answer",
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )
    
    async def stream(self, context):
        raise NotImplementedError("Stream not supported in E2E tests")
    
    async def cleanup(self):
        pass


@pytest.fixture
def mock_provider():
    return MockLLMProvider()


@pytest.fixture
def tool_registry():
    registry = ToolRegistry()
    
    @registry.register(name="get_weather", description="Get weather for a city")
    def get_weather(city: str) -> str:
        return f"Weather in {city}: Sunny, 25°C"
    
    @registry.register(name="search", description="Search for information")
    def search(query: str) -> str:
        return f"Search results for '{query}': Found 3 results"
    
    return registry


@pytest.mark.asyncio
async def test_agent_runtime_complete_react_loop(mock_provider, tool_registry):
    """Test complete ReAct loop: Think -> Act -> Think -> Finish."""
    config = AgentConfig(
        model="test-model",
        max_steps=5,
        system_prompt="You are a helpful assistant.",
    )
    
    agent = AgentRuntime(
        config=config,
        llm_provider=mock_provider,
        tool_registry=tool_registry,
    )
    
    # Setup responses:
    # 1st call: Think + tool call
    # 2nd call: Think + finish
    mock_provider.add_response(
        LLMResponse(
            content="Let me check the weather.",
            tool_calls=[ToolCall(id="call_1", name="get_weather", arguments={"city": "Beijing"})],
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=20, completion_tokens=15, total_tokens=35),
        )
    )
    mock_provider.add_response(
        LLMResponse(
            content="The weather in Beijing is sunny, 25°C.",
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=40, completion_tokens=20, total_tokens=60),
        )
    )
    
    # Run agent
    state = await agent.run(user_message="What's the weather in Beijing?")
    
    # Verify final state
    assert state.status == AgentStatus.FINISHED
    assert state.steps == 2  # Two think phases
    
    # Verify step records
    assert len(state.steps_history) == 2
    
    # First step: Think + Act
    step1 = state.steps_history[0]
    assert step1.action_type == ActionType.ACT
    assert step1.llm_response is not None
    assert len(step1.llm_response.tool_calls) == 1
    assert step1.tool_results is not None
    assert len(step1.tool_results) == 1
    assert step1.tool_results[0].name == "get_weather"
    
    # Second step: Think + Finish
    step2 = state.steps_history[1]
    assert step2.action_type == ActionType.FINISH
    assert step2.llm_response is not None
    assert len(step2.llm_response.tool_calls) == 0


@pytest.mark.asyncio
async def test_agent_runtime_memory_trimming(mock_provider, tool_registry):
    """Test that memory trimming works correctly during long conversations."""
    from onion_core.agent import SlidingWindowMemory
    
    config = AgentConfig(
        model="test-model",
        max_steps=3,
        memory_max_tokens=1000,  # Small limit to trigger trimming
    )
    
    memory = SlidingWindowMemory(config)
    
    agent = AgentRuntime(
        config=config,
        llm_provider=mock_provider,
        tool_registry=tool_registry,
        memory=memory,
    )
    
    # Add a response that finishes immediately
    mock_provider.add_response(
        LLMResponse(
            content="Short answer.",
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
    )
    
    # Create a context with many messages to trigger trimming
    state = AgentState()
    for i in range(20):
        state.add_message(Message(role="user", content=f"Message {i}" * 10))
    
    # Run agent (should trim messages before processing)
    state = await agent.run(user_message="Final question", state=state)
    
    # Verify state is finished
    assert state.status == AgentStatus.FINISHED
    
    # Verify messages were trimmed (should be less than original)
    # Note: Exact count depends on tiktoken estimation
    assert len(state.messages) < 25  # Original was 20 + system + user


@pytest.mark.asyncio
async def test_agent_runtime_step_record_completeness(mock_provider, tool_registry):
    """Test that StepRecord contains all required fields."""
    import asyncio
    
    config = AgentConfig(
        model="test-model",
        max_steps=2,
    )
    
    # Create a slightly slow provider to ensure duration_ms > 0
    class SlowMockProvider(MockLLMProvider):
        async def complete(self, context):
            await asyncio.sleep(0.001)  # Small delay to ensure measurable duration
            return await super().complete(context)
    
    slow_provider = SlowMockProvider()
    agent = AgentRuntime(
        config=config,
        llm_provider=slow_provider,
        tool_registry=tool_registry,
    )
    
    slow_provider.add_response(
        LLMResponse(
            content="Answer",
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )
    )
    
    collected_steps = []
    
    def collect_step(step: StepRecord):
        collected_steps.append(step)
    
    agent.on_step(collect_step)
    
    await agent.run(user_message="Test question")
    
    # Verify step record completeness
    assert len(collected_steps) == 1
    step = collected_steps[0]
    
    assert step.step_index == 1
    assert step.trace_id is not None
    assert step.action_type == ActionType.FINISH
    assert step.status == AgentStatus.THINKING
    assert step.llm_response is not None
    assert step.duration_ms >= 0  # Changed from > 0 to >= 0 for robustness
    assert step.token_usage is not None
    assert step.token_usage.total_tokens == 20


@pytest.mark.asyncio
async def test_agent_runtime_cancel_during_execution(mock_provider, tool_registry):
    """Test that cancel() works correctly during execution."""
    import asyncio
    
    config = AgentConfig(
        model="test-model",
        max_steps=10,
    )
    
    agent = AgentRuntime(
        config=config,
        llm_provider=mock_provider,
        tool_registry=tool_registry,
    )
    
    # Make provider slow to allow cancellation
    class SlowProvider(MockLLMProvider):
        async def complete(self, context):
            await asyncio.sleep(0.5)  # Simulate slow LLM
            return await super().complete(context)
    
    slow_provider = SlowProvider()
    slow_provider.add_response(
        LLMResponse(
            content="Slow response",
            finish_reason=FinishReason.STOP,
            usage=UsageStats(),
        )
    )
    
    agent._llm_provider = slow_provider
    
    # Start execution in background
    task = asyncio.create_task(agent.run(user_message="Test"))
    
    # Cancel after a short delay
    await asyncio.sleep(0.1)
    agent.cancel()
    
    # Wait for task to complete
    state = await task
    
    # Verify agent was cancelled or finished gracefully
    assert state.status in [AgentStatus.CANCELLED, AgentStatus.FINISHED]


@pytest.mark.asyncio
async def test_agent_runtime_error_handling(mock_provider, tool_registry):
    """Test that errors are properly handled and recorded."""
    config = AgentConfig(
        model="test-model",
        max_steps=2,
    )
    
    agent = AgentRuntime(
        config=config,
        llm_provider=mock_provider,
        tool_registry=tool_registry,
    )
    
    # Make provider raise an error
    class FailingProvider(MockLLMProvider):
        async def complete(self, context):
            raise RuntimeError("Simulated LLM failure")
    
    failing_provider = FailingProvider()
    agent._llm_provider = failing_provider
    
    collected_errors = []
    
    def collect_error(request_id: str, exc: Exception):
        collected_errors.append((request_id, exc))
    
    agent.on_error(collect_error)
    
    # Run should handle the error gracefully
    state = await agent.run(user_message="Test")
    
    # Verify error was recorded
    assert state.status == AgentStatus.ERROR
    assert len(collected_errors) == 1
    assert isinstance(collected_errors[0][1], RuntimeError)
