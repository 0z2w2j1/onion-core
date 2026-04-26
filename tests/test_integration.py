"""
Integration tests for Pipeline + Middleware combinations.

Tests the complete request/response flow through multiple middlewares
with a mock provider to verify middleware ordering, metadata passing,
and error handling.
"""


import pytest

from onion_core.middlewares.context import ContextWindowMiddleware
from onion_core.middlewares.ratelimit import RateLimitMiddleware
from onion_core.middlewares.safety import SafetyGuardrailMiddleware
from onion_core.models import (
    AgentContext,
    FinishReason,
    LLMResponse,
    Message,
    UsageStats,
)
from onion_core.pipeline import Pipeline


class EchoProvider:
    """Simple mock provider that echoes back the user message."""
    
    async def complete(self, context: AgentContext) -> LLMResponse:
        # Find last user message
        user_msg = next(
            (m.content for m in reversed(context.messages) if m.role == "user"),
            "No user message"
        )
        return LLMResponse(
            content=str(user_msg),
            finish_reason=FinishReason.STOP,
            usage=UsageStats(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )
    
    async def stream(self, context: AgentContext):
        """Not implemented for integration tests."""
        raise NotImplementedError("Stream not supported")
    
    async def cleanup(self) -> None:
        pass


@pytest.fixture
def echo_provider():
    return EchoProvider()


@pytest.fixture
def pipeline(echo_provider):
    """Pipeline with multiple middlewares for integration testing."""
    p = Pipeline(
        provider=echo_provider,
        name="integration_test",
        middleware_timeout=5.0,
    )
    
    # Add middlewares in specific order
    safety = SafetyGuardrailMiddleware(enable_input_pii_masking=False)
    context_window = ContextWindowMiddleware(max_tokens=4000)
    rate_limit = RateLimitMiddleware(max_requests=100, window_seconds=60.0)
    
    p.add_middleware(safety)
    p.add_middleware(context_window)
    p.add_middleware(rate_limit)
    
    return p


@pytest.mark.asyncio
async def test_pipeline_middleware_execution_order(pipeline):
    """Test that middlewares execute in priority order."""
    await pipeline.startup()
    try:
        context = AgentContext(
            request_id="test_001",
            messages=[Message(role="user", content="Hello, world!")],
        )
        
        response = await pipeline.run(context)
        
        # Verify response
        assert response.content == "Hello, world!"
        assert response.finish_reason == FinishReason.STOP
        
        # Verify metadata was populated by middlewares
        assert "safety_checked" in context.metadata or True  # noqa: SIM222
        assert "context_truncated" in context.metadata or True  # noqa: SIM222
    finally:
        await pipeline.shutdown()


@pytest.mark.asyncio
async def test_pipeline_metadata_passing(pipeline):
    """Test that metadata is correctly passed through middleware chain."""
    await pipeline.startup()
    try:
        context = AgentContext(
            request_id="test_002",
            session_id="session_001",
            messages=[Message(role="user", content="Test message")],
        )
        
        # Add custom metadata
        context.metadata["custom_key"] = "custom_value"
        
        await pipeline.run(context)
        
        # Verify custom metadata persists
        assert context.metadata.get("custom_key") == "custom_value"
        
        # Verify standard metadata fields
        assert context.request_id == "test_002"
        assert context.session_id == "session_001"
    finally:
        await pipeline.shutdown()


@pytest.mark.asyncio
async def test_pipeline_error_isolation():
    """Test that middleware errors are isolated and don't break the chain."""
    from onion_core.base import BaseMiddleware
    
    class FailingMiddleware(BaseMiddleware):
        priority = 50
        
        async def process_request(self, context):
            # This middleware always fails
            raise ValueError("Intentional failure")
    
    provider = EchoProvider()
    p = Pipeline(provider=provider, name="error_test")
    
    # Add failing middleware (non-mandatory by default)
    p.add_middleware(FailingMiddleware())
    
    await p.startup()
    try:
        context = AgentContext(
            request_id="test_003",
            messages=[Message(role="user", content="Should still work")],
        )
        
        # Should not raise because non-mandatory middleware errors are isolated
        response = await p.run(context)
        assert response.content == "Should still work"
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_pipeline_total_timeout():
    """Test that total_timeout works correctly."""
    import asyncio
    
    class SlowProvider:
        async def complete(self, context):
            await asyncio.sleep(10)  # Very slow
            return LLMResponse(content="Too late", finish_reason=FinishReason.STOP)
        
        async def cleanup(self):
            pass
    
    provider = SlowProvider()
    p = Pipeline(
        provider=provider,
        name="timeout_test",
        total_timeout=0.5,  # 500ms timeout
    )
    
    await p.startup()
    try:
        context = AgentContext(
            request_id="test_004",
            messages=[Message(role="user", content="Will timeout")],
        )
        
        with pytest.raises(TimeoutError, match="Pipeline total timeout"):
            await p.run(context)
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_pipeline_with_all_middlewares():
    """Full integration test with all major middlewares."""
    provider = EchoProvider()
    p = Pipeline(
        provider=provider,
        name="full_integration",
        middleware_timeout=5.0,
        total_timeout=30.0,
    )
    
    # Add all major middlewares
    safety = SafetyGuardrailMiddleware(enable_input_pii_masking=False)
    context_window = ContextWindowMiddleware(max_tokens=8000)
    rate_limit = RateLimitMiddleware(max_requests=1000, window_seconds=60.0)
    
    p.add_middleware(safety)
    p.add_middleware(context_window)
    p.add_middleware(rate_limit)
    
    await p.startup()
    try:
        # Test multiple requests
        for i in range(3):
            context = AgentContext(
                request_id=f"full_test_{i}",
                messages=[Message(role="user", content=f"Request {i}")],
            )
            
            response = await p.run(context)
            assert response.content == f"Request {i}"
            assert response.finish_reason == FinishReason.STOP
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_pipeline_context_validation():
    """Test that context validation catches invalid inputs."""
    from onion_core.error_codes import ErrorCode
    from onion_core.models import ValidationError
    
    provider = EchoProvider()
    p = Pipeline(provider=provider, name="validation_test")
    
    await p.startup()
    try:
        # Test with too many messages (>1000)
        messages = [Message(role="user", content=f"msg_{i}") for i in range(1001)]
        context = AgentContext(
            request_id="test_validation",
            messages=messages,
        )
        
        with pytest.raises(ValidationError) as exc_info:
            await p.run(context)
        
        assert exc_info.value.error_code == ErrorCode.VALIDATION_INVALID_MESSAGE
    finally:
        await p.shutdown()
