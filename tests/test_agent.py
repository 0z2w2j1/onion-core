"""AgentLoop 测试。"""

from __future__ import annotations

import pytest

from onion_core import (
    AgentContext,
    EchoProvider,
    LLMResponse,
    Pipeline,
    ToolCall,
)
from onion_core.agent import AgentLoop, AgentLoopError
from onion_core.tools import ToolRegistry

from .conftest import make_context

# ── 辅助 Provider ─────────────────────────────────────────────────────────────

class SingleToolProvider(EchoProvider):
    """第一轮返回 tool_call，第二轮返回 stop。"""

    def __init__(self, tool_name: str = "ping", tool_args: dict | None = None):
        super().__init__()
        self._tool_name = tool_name
        self._tool_args = tool_args or {}
        self._calls = 0

    async def complete(self, context: AgentContext) -> LLMResponse:
        self._calls += 1
        if self._calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="tc1", name=self._tool_name, arguments=self._tool_args)],
                finish_reason="tool_calls",
            )
        return LLMResponse(content="done", finish_reason="stop")


class InfiniteToolProvider(EchoProvider):
    """永远返回 tool_calls，用于测试 max_turns。"""

    async def complete(self, context: AgentContext) -> LLMResponse:
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="tc1", name="ping", arguments={})],
            finish_reason="tool_calls",
        )


class SequenceToolProvider(EchoProvider):
    """按预定义序列返回响应。"""

    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = responses
        self._idx = 0

    async def complete(self, context: AgentContext) -> LLMResponse:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return LLMResponse(content="done", finish_reason="stop")


# ── 测试 ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_loop_no_tools_returns_immediately():
    """LLM 直接返回 stop，AgentLoop 应在第一轮结束。"""
    p = Pipeline(provider=EchoProvider(reply="hi"))
    loop = AgentLoop(pipeline=p)
    ctx = make_context()
    resp = await loop.run(ctx)
    assert resp.finish_reason == "stop"
    assert resp.content == "hi"


@pytest.mark.asyncio
async def test_agent_loop_executes_tool_and_continues():
    """AgentLoop 应执行工具调用并在第二轮拿到最终回复。"""
    registry = ToolRegistry()

    @registry.register
    async def ping() -> str:
        return "pong"

    p = Pipeline(provider=SingleToolProvider("ping"))
    loop = AgentLoop(pipeline=p, registry=registry)
    ctx = make_context()
    resp = await loop.run(ctx)

    assert resp.finish_reason == "stop"
    assert resp.content == "done"
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "pong"


@pytest.mark.asyncio
async def test_agent_loop_unknown_tool_returns_error_result():
    """工具不存在时，ToolRegistry 返回 error ToolResult，循环不应崩溃。"""
    p = Pipeline(provider=SingleToolProvider("nonexistent"))
    loop = AgentLoop(pipeline=p)
    ctx = make_context()
    resp = await loop.run(ctx)
    assert resp.finish_reason == "stop"
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "Error" in tool_msgs[0].content


@pytest.mark.asyncio
async def test_agent_loop_max_turns_no_raise():
    """达到 max_turns 时默认不抛出，返回最后一次 LLMResponse。"""
    p = Pipeline(provider=InfiniteToolProvider())
    loop = AgentLoop(pipeline=p, max_turns=3, raise_on_max_turns=False)
    ctx = make_context()
    resp = await loop.run(ctx)
    assert resp is not None
    assert resp.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_agent_loop_max_turns_raises():
    """raise_on_max_turns=True 时应抛出 AgentLoopError。"""
    p = Pipeline(provider=InfiniteToolProvider())
    loop = AgentLoop(pipeline=p, max_turns=2, raise_on_max_turns=True)
    ctx = make_context()
    with pytest.raises(AgentLoopError):
        await loop.run(ctx)


@pytest.mark.asyncio
async def test_agent_loop_tool_with_context_injection():
    """工具函数接受 context 参数时应自动注入。"""
    registry = ToolRegistry()

    @registry.register
    async def get_session_id(context: AgentContext) -> str:
        return context.session_id

    p = Pipeline(provider=SingleToolProvider("get_session_id"))
    loop = AgentLoop(pipeline=p, registry=registry)
    ctx = make_context()
    await loop.run(ctx)

    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert tool_msgs[0].content == ctx.session_id


@pytest.mark.asyncio
async def test_agent_loop_pipeline_middleware_applied():
    """Pipeline 中间件（如 ObservabilityMiddleware）应在 AgentLoop 中正常工作。"""
    from onion_core.middlewares import ObservabilityMiddleware

    p = Pipeline(provider=EchoProvider(reply="ok")).add_middleware(ObservabilityMiddleware())
    loop = AgentLoop(pipeline=p)
    ctx = make_context()
    await loop.run(ctx)
    assert "duration_s" in ctx.metadata


@pytest.mark.asyncio
async def test_agent_loop_allows_same_args_across_turns():
    """同参数工具调用在不同轮次应可重复执行。"""
    registry = ToolRegistry()
    calls: list[str] = []

    @registry.register
    async def ping(city: str) -> str:
        calls.append(city)
        return f"pong:{city}"

    provider = SequenceToolProvider(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="tc1", name="ping", arguments={"city": "shanghai"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="tc2", name="ping", arguments={"city": "shanghai"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="ok", finish_reason="stop"),
        ]
    )
    loop = AgentLoop(pipeline=Pipeline(provider=provider), registry=registry)
    ctx = make_context()
    resp = await loop.run(ctx)

    assert resp.finish_reason == "stop"
    assert calls == ["shanghai", "shanghai"]


@pytest.mark.asyncio
async def test_agent_loop_dedups_duplicate_tool_calls_within_same_response():
    """同一响应内重复 tool_call（相同 id）只执行一次。"""
    registry = ToolRegistry()
    execution_count = 0

    @registry.register
    async def ping() -> str:
        nonlocal execution_count
        execution_count += 1
        return "pong"

    provider = SequenceToolProvider(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="same-id", name="ping", arguments={}),
                    ToolCall(id="same-id", name="ping", arguments={}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="ok", finish_reason="stop"),
        ]
    )
    loop = AgentLoop(pipeline=Pipeline(provider=provider), registry=registry)
    ctx = make_context()
    await loop.run(ctx)

    assert execution_count == 1


@pytest.mark.asyncio
async def test_agent_loop_dedup_policy_strict_from_context_config():
    """strict 策略下，同一响应中同 name+args（不同 id）应去重。"""
    registry = ToolRegistry()
    execution_count = 0

    @registry.register
    async def ping(city: str) -> str:
        nonlocal execution_count
        execution_count += 1
        return f"pong:{city}"

    provider = SequenceToolProvider(
        responses=[
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="id-1", name="ping", arguments={"city": "bj"}),
                    ToolCall(id="id-2", name="ping", arguments={"city": "bj"}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="ok", finish_reason="stop"),
        ]
    )
    loop = AgentLoop(pipeline=Pipeline(provider=provider), registry=registry)
    ctx = make_context()
    ctx.config["tool_call_dedup_policy"] = "strict"
    await loop.run(ctx)

    assert execution_count == 1
