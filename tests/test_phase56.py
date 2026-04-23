"""阶段五六新增组件测试：可观测性、ToolRegistry、RateLimitMiddleware。"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline, ToolCall, ToolResult
from onion_core.middlewares import RateLimitMiddleware
from onion_core.middlewares.ratelimit import RateLimitExceeded
from onion_core.observability.logging import JsonFormatter, configure_logging
from onion_core.tools import ToolRegistry

from .conftest import make_context


# ── JsonFormatter ─────────────────────────────────────────────────────────────

def test_json_formatter_basic():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="onion_core.test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="[abc123] Test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "INFO"
    assert data["logger"] == "onion_core.test"
    assert "Test message" in data["message"]
    assert data["request_id"] == "abc123"
    assert "timestamp" in data


def test_json_formatter_with_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test", level=logging.ERROR,
        pathname="", lineno=0,
        msg="Something failed", args=(), exc_info=exc_info,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "exc_info" in data
    assert "ValueError" in data["exc_info"]


def test_configure_logging_returns_logger():
    logger = configure_logging(level="DEBUG", json_format=True, logger_name="onion_core.test_cfg")
    assert logger.name == "onion_core.test_cfg"
    assert logger.level == logging.DEBUG


# ── ToolRegistry ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_registry_register_and_execute():
    registry = ToolRegistry()

    @registry.register
    async def greet(name: str) -> str:
        """Say hello."""
        return f"Hello, {name}!"

    tc = ToolCall(id="t1", name="greet", arguments={"name": "World"})
    result = await registry.execute(tc)

    assert isinstance(result, ToolResult)
    assert result.result == "Hello, World!"
    assert not result.is_error


@pytest.mark.asyncio
async def test_tool_registry_sync_function():
    registry = ToolRegistry()

    @registry.register
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    tc = ToolCall(id="t1", name="add", arguments={"a": 3, "b": 4})
    result = await registry.execute(tc)
    assert result.result == "7"


@pytest.mark.asyncio
async def test_tool_registry_unknown_tool():
    registry = ToolRegistry()
    tc = ToolCall(id="t1", name="nonexistent", arguments={})
    result = await registry.execute(tc)
    assert result.is_error
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_tool_registry_exception_captured():
    registry = ToolRegistry()

    @registry.register
    async def failing_tool(x: str) -> str:
        raise RuntimeError("tool failed")

    tc = ToolCall(id="t1", name="failing_tool", arguments={"x": "test"})
    result = await registry.execute(tc)
    assert result.is_error
    assert "RuntimeError" in result.error


@pytest.mark.asyncio
async def test_tool_registry_context_injection():
    registry = ToolRegistry()

    @registry.register
    async def get_session(context: AgentContext) -> str:
        return context.session_id

    ctx = make_context()
    tc = ToolCall(id="t1", name="get_session", arguments={})
    result = await registry.execute(tc, context=ctx)
    assert result.result == ctx.session_id


def test_tool_registry_openai_schema():
    registry = ToolRegistry()

    @registry.register
    async def search(query: str, max_results: int = 5) -> str:
        """Search the web."""
        return ""

    tools = registry.to_openai_tools()
    assert len(tools) == 1
    fn = tools[0]["function"]
    assert fn["name"] == "search"
    assert fn["description"] == "Search the web."
    assert "query" in fn["parameters"]["properties"]
    assert "query" in fn["parameters"]["required"]
    assert "max_results" not in fn["parameters"]["required"]


def test_tool_registry_anthropic_schema():
    registry = ToolRegistry()

    @registry.register
    async def lookup(term: str) -> str:
        """Look up a term."""
        return ""

    tools = registry.to_anthropic_tools()
    assert tools[0]["name"] == "lookup"
    assert "input_schema" in tools[0]


@pytest.mark.asyncio
async def test_tool_registry_decorator_with_name():
    registry = ToolRegistry()

    @registry.register(name="custom_name", description="Custom desc")
    async def my_func(x: str) -> str:
        return x

    assert "custom_name" in registry.tool_names
    assert "my_func" not in registry.tool_names


# ── RateLimitMiddleware ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_allows_under_limit():
    p = Pipeline(provider=EchoProvider()).add_middleware(
        RateLimitMiddleware(max_requests=5, window_seconds=60)
    )
    ctx = make_context()
    resp = await p.run(ctx)
    assert isinstance(resp, LLMResponse)
    assert ctx.metadata["rate_limit_remaining"] == 4


@pytest.mark.asyncio
async def test_rate_limit_blocks_over_limit():
    mw = RateLimitMiddleware(max_requests=3, window_seconds=60)
    p = Pipeline(provider=EchoProvider()).add_middleware(mw)

    for _ in range(3):
        ctx = AgentContext(
            session_id="test-session",
            messages=[Message(role="user", content="hi")],
        )
        await p.run(ctx)

    ctx = AgentContext(
        session_id="test-session",
        messages=[Message(role="user", content="hi")],
    )
    with pytest.raises(RateLimitExceeded):
        await p.run(ctx)


@pytest.mark.asyncio
async def test_rate_limit_different_sessions_independent():
    mw = RateLimitMiddleware(max_requests=2, window_seconds=60)
    p = Pipeline(provider=EchoProvider()).add_middleware(mw)

    for _ in range(2):
        ctx = AgentContext(session_id="session-a", messages=[Message(role="user", content="hi")])
        await p.run(ctx)

    ctx_b = AgentContext(session_id="session-b", messages=[Message(role="user", content="hi")])
    resp = await p.run(ctx_b)
    assert isinstance(resp, LLMResponse)


@pytest.mark.asyncio
async def test_rate_limit_window_expiry():
    mw = RateLimitMiddleware(max_requests=1, window_seconds=0.1)
    p = Pipeline(provider=EchoProvider()).add_middleware(mw)

    ctx1 = AgentContext(session_id="s1", messages=[Message(role="user", content="hi")])
    await p.run(ctx1)

    ctx2 = AgentContext(session_id="s1", messages=[Message(role="user", content="hi")])
    with pytest.raises(RateLimitExceeded):
        await p.run(ctx2)

    await asyncio.sleep(0.15)

    ctx3 = AgentContext(session_id="s1", messages=[Message(role="user", content="hi")])
    resp = await p.run(ctx3)
    assert isinstance(resp, LLMResponse)


def test_rate_limit_get_usage():
    mw = RateLimitMiddleware(max_requests=10, window_seconds=60)
    usage = mw.get_usage("unknown-session")
    assert usage["requests_in_window"] == 0
    assert usage["remaining"] == 10


# ── MetricsMiddleware（no-op 模式）────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_middleware_noop():
    from onion_core.observability.metrics import MetricsMiddleware
    p = Pipeline(provider=EchoProvider()).add_middleware(MetricsMiddleware())
    ctx = make_context()
    resp = await p.run(ctx)
    assert isinstance(resp, LLMResponse)


# ── TracingMiddleware（no-op 模式）────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tracing_middleware_noop():
    from onion_core.observability.tracing import TracingMiddleware
    p = Pipeline(provider=EchoProvider()).add_middleware(TracingMiddleware())
    ctx = make_context()
    resp = await p.run(ctx)
    assert isinstance(resp, LLMResponse)
    assert "_otel_span" not in ctx.metadata
