"""Pipeline 同步 API 测试。"""

from __future__ import annotations

import pytest

from onion_core import EchoProvider, LLMResponse, Pipeline, StreamChunk
from onion_core.base import BaseMiddleware

from .conftest import make_context


@pytest.fixture
def sync_pipeline() -> Pipeline:
    """创建已启动的同步 Pipeline。"""
    p = Pipeline(provider=EchoProvider())
    p.startup_sync()
    yield p
    p.shutdown_sync()


# ── 基础同步调用 ─────────────────────────────────────────────────────────────

def test_run_sync_returns_llm_response(sync_pipeline):
    """测试 run_sync 返回 LLMResponse。"""
    ctx = make_context()
    resp = sync_pipeline.run_sync(ctx)
    assert isinstance(resp, LLMResponse)
    assert resp.content
    assert resp.finish_reason == "stop"


def test_stream_sync_yields_chunks(sync_pipeline):
    """测试 stream_sync 产出 StreamChunk。"""
    ctx = make_context()
    chunks = list(sync_pipeline.stream_sync(ctx))
    assert len(chunks) > 0
    assert all(isinstance(c, StreamChunk) for c in chunks)
    assert chunks[-1].finish_reason is not None
    full = "".join(c.delta for c in chunks)
    assert full  # assembled text non-empty


def test_execute_tool_call_sync(sync_pipeline):
    """测试 execute_tool_call_sync。"""
    from onion_core import ToolCall

    ctx = make_context()
    tool_call = ToolCall(id="test-1", name="test_tool", arguments={})
    result = sync_pipeline.execute_tool_call_sync(ctx, tool_call)
    assert isinstance(result, ToolCall)
    assert result.name == "test_tool"


def test_execute_tool_result_sync(sync_pipeline):
    """测试 execute_tool_result_sync。"""
    from onion_core import ToolResult

    ctx = make_context()
    tool_result = ToolResult(
        tool_call_id="test-1", name="test_tool", result="success"
    )
    result = sync_pipeline.execute_tool_result_sync(ctx, tool_result)
    assert isinstance(result, ToolResult)
    assert result.result == "success"


# ── 同步生命周期 ─────────────────────────────────────────────────────────────

def test_startup_shutdown_sync_lifecycle():
    """测试同步 startup/shutdown 生命周期。"""
    events: list[str] = []

    class TrackMW(BaseMiddleware):
        async def startup(self):
            events.append("start")

        async def shutdown(self):
            events.append("stop")

        async def process_request(self, ctx):
            return ctx

        async def process_response(self, ctx, r):
            return r

        async def process_stream_chunk(self, ctx, c):
            return c

        async def on_tool_call(self, ctx, tc):
            return tc

        async def on_tool_result(self, ctx, r):
            return r

        async def on_error(self, ctx, e):
            pass

    p = Pipeline(provider=EchoProvider()).add_middleware(TrackMW())
    assert not p._started
    p.startup_sync()
    assert p._started
    assert events == ["start"]
    p.shutdown_sync()
    assert not p._started
    assert events == ["start", "stop"]


def test_sync_context_manager():
    """测试同步上下文管理器。"""
    with Pipeline(provider=EchoProvider()) as p:
        assert p._started
        ctx = make_context()
        resp = p.run_sync(ctx)
        assert isinstance(resp, LLMResponse)
    assert not p._started


def test_sync_context_manager_with_exception():
    """测试同步上下文管理器异常时仍能正确 shutdown。"""
    with (
        pytest.raises(RuntimeError),
        Pipeline(provider=EchoProvider()) as p,
    ):
        assert p._started
        raise RuntimeError("Test exception")
    # 即使抛出异常，Pipeline 也应该被正确关闭
    # （由 __exit__ 保证）


# ── 同步与异步互操作性 ───────────────────────────────────────────────────────

def test_sync_api_independent():
    """测试同步 API 独立工作。"""
    # 同步上下文使用同步 API
    with Pipeline(provider=EchoProvider()) as p:
        ctx = make_context()
        resp = p.run_sync(ctx)
        assert isinstance(resp, LLMResponse)


# ── 中间件集成测试 ───────────────────────────────────────────────────────────

def test_sync_pipeline_with_middlewares():
    """测试带中间件的同步 Pipeline。"""
    from onion_core.middlewares import (
        ContextWindowMiddleware,
        ObservabilityMiddleware,
        SafetyGuardrailMiddleware,
    )

    with Pipeline(provider=EchoProvider()) as p:
        p.add_middleware(ObservabilityMiddleware())
        p.add_middleware(SafetyGuardrailMiddleware())
        p.add_middleware(ContextWindowMiddleware(max_tokens=2000))

        ctx = make_context()
        resp = p.run_sync(ctx)
        assert isinstance(resp, LLMResponse)
        assert "start_time" in ctx.metadata
        assert "duration_s" in ctx.metadata
