"""Pipeline 核心行为测试。"""

from __future__ import annotations

import asyncio

import pytest

from onion_core import (
    AgentContext,
    EchoProvider,
    LLMResponse,
    Message,
    Pipeline,
    StreamChunk,
    ToolCall,
    ToolResult,
)
from onion_core.base import BaseMiddleware
from onion_core.models import ValidationError

from .conftest import make_context

# ── 基础调用 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_returns_llm_response(started_pipeline, simple_context):
    resp = await started_pipeline.run(simple_context)
    assert isinstance(resp, LLMResponse)
    assert resp.content
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_yields_chunks(started_pipeline, simple_context):
    chunks = [c async for c in started_pipeline.stream(simple_context)]
    assert len(chunks) > 0
    assert all(isinstance(c, StreamChunk) for c in chunks)
    assert chunks[-1].finish_reason is not None
    full = "".join(c.delta for c in chunks)
    assert full  # assembled text non-empty


@pytest.mark.asyncio
async def test_metadata_populated(started_pipeline, simple_context):
    await started_pipeline.run(simple_context)
    assert "start_time" in simple_context.metadata
    assert "duration_s" in simple_context.metadata
    assert simple_context.metadata["context_truncated"] is False


# ── 生命周期 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_shutdown_lifecycle():
    events: list[str] = []

    class TrackMW(BaseMiddleware):
        async def startup(self): events.append("start")
        async def shutdown(self): events.append("stop")
        async def process_request(self, ctx): return ctx
        async def process_response(self, ctx, r): return r
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    p = Pipeline(provider=EchoProvider()).add_middleware(TrackMW())
    assert not p._started
    await p.startup()
    assert p._started
    assert events == ["start"]
    await p.shutdown()
    assert not p._started
    assert events == ["start", "stop"]


@pytest.mark.asyncio
async def test_context_manager():
    async with Pipeline(provider=EchoProvider()) as p:
        assert p._started
        ctx = make_context()
        resp = await p.run(ctx)
        assert isinstance(resp, LLMResponse)
    assert not p._started


@pytest.mark.asyncio
async def test_startup_idempotent():
    count = 0

    class CountMW(BaseMiddleware):
        async def startup(self):
            nonlocal count
            count += 1
        async def process_request(self, ctx): return ctx
        async def process_response(self, ctx, r): return r
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    p = Pipeline(provider=EchoProvider()).add_middleware(CountMW())
    await p.startup()
    await p.startup()  # 第二次应被忽略
    assert count == 1
    await p.shutdown()


@pytest.mark.asyncio
async def test_startup_rollback_on_failure():
    """startup 失败时，已启动的中间件应被回滚 shutdown。"""
    stopped: list[str] = []

    class GoodMW(BaseMiddleware):
        priority = 100  # 先启动
        async def shutdown(self): stopped.append("good")
        async def process_request(self, ctx): return ctx
        async def process_response(self, ctx, r): return r
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    class BadMW(BaseMiddleware):
        priority = 200  # 后启动，失败
        async def startup(self): raise RuntimeError("startup failed")
        async def process_request(self, ctx): return ctx
        async def process_response(self, ctx, r): return r
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    p = Pipeline(provider=EchoProvider()).add_middleware(GoodMW()).add_middleware(BadMW())
    with pytest.raises(RuntimeError, match="startup failed"):
        await p.startup()
    assert "good" in stopped  # GoodMW 被回滚


# ── 优先级排序 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_priority_ordering():
    req_order: list[str] = []
    resp_order: list[str] = []

    def make_mw(label: str, prio: int):
        class PMW(BaseMiddleware):
            priority = prio
            @property
            def name(self): return label
            async def process_request(self, ctx):
                req_order.append(label)
                return ctx
            async def process_response(self, ctx, r):
                resp_order.append(label)
                return r
            async def process_stream_chunk(self, ctx, c): return c
            async def on_tool_call(self, ctx, tc): return tc
            async def on_tool_result(self, ctx, r): return r
            async def on_error(self, ctx, e): pass
        return PMW()

    p = (
        Pipeline(provider=EchoProvider())
        .add_middleware(make_mw("C", 300))
        .add_middleware(make_mw("A", 100))
        .add_middleware(make_mw("B", 200))
    )
    await p.run(make_context())
    assert req_order == ["A", "B", "C"]
    assert resp_order == ["C", "B", "A"]


# ── 超时控制 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_middleware_timeout():
    class SlowMW(BaseMiddleware):
        is_mandatory = True  # 强制要求，超时应抛出异常
        async def process_request(self, ctx):
            await asyncio.sleep(10)
            return ctx
        async def process_response(self, ctx, r): return r
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    p = Pipeline(provider=EchoProvider(), middleware_timeout=0.05).add_middleware(SlowMW())
    with pytest.raises(asyncio.TimeoutError):
        await p.run(make_context())


@pytest.mark.asyncio
async def test_non_mandatory_middleware_isolation():
    class BuggyMW(BaseMiddleware):
        is_mandatory = False  # 非强制，失败应被隔离
        async def process_request(self, ctx):
            raise RuntimeError("I am a non-fatal bug")
        async def process_response(self, ctx, r): return r

    p = Pipeline(provider=EchoProvider()).add_middleware(BuggyMW())
    # 不应抛出 RuntimeError
    resp = await p.run(make_context())
    assert isinstance(resp, LLMResponse)


@pytest.mark.asyncio
async def test_provider_timeout():
    class SlowProvider(EchoProvider):
        async def complete(self, context):
            await asyncio.sleep(10)
            return await super().complete(context)

    p = Pipeline(provider=SlowProvider(), provider_timeout=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await p.run(make_context())


# ── 重试 ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_retry():
    call_count = 0

    class FlakyProvider(EchoProvider):
        async def complete(self, context):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient error")
            return await super().complete(context)

    p = Pipeline(provider=FlakyProvider(), max_retries=3, retry_base_delay=0.01)
    resp = await p.run(make_context())
    assert isinstance(resp, LLMResponse)
    assert call_count == 3


@pytest.mark.asyncio
async def test_provider_retry_exhausted():
    class AlwaysFailProvider(EchoProvider):
        async def complete(self, context):
            raise ConnectionError("always fails")

    p = Pipeline(provider=AlwaysFailProvider(), max_retries=2, retry_base_delay=0.01)
    with pytest.raises(ConnectionError):
        await p.run(make_context())


# ── 工具调用 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_call_passthrough(started_pipeline, simple_context):
    tc = ToolCall(id="t1", name="search", arguments={"q": "python"})
    result = await started_pipeline.execute_tool_call(simple_context, tc)
    assert isinstance(result, ToolCall)
    assert result.arguments == {"q": "python"}


@pytest.mark.asyncio
async def test_tool_result_passthrough(started_pipeline, simple_context):
    tr = ToolResult(tool_call_id="t1", name="search", result="found 10 results")
    result = await started_pipeline.execute_tool_result(simple_context, tr)
    assert isinstance(result, ToolResult)


# ── 洋葱模型逆序 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("hook,expected", [
    ("response", ["B", "A"]),
    ("tool_result", ["B", "A"]),
])
async def test_onion_reverse_order(hook, expected):
    order: list[str] = []

    def make_tracker(label: str):
        class T(BaseMiddleware):
            @property
            def name(self): return label
            async def process_request(self, ctx): return ctx
            async def process_response(self, ctx, r):
                if hook == "response":
                    order.append(label)
                return r
            async def process_stream_chunk(self, ctx, c): return c
            async def on_tool_call(self, ctx, tc): return tc
            async def on_tool_result(self, ctx, r):
                if hook == "tool_result":
                    order.append(label)
                return r
            async def on_error(self, ctx, e): pass
        return T()

    p = Pipeline(provider=EchoProvider()).add_middleware(make_tracker("A")).add_middleware(make_tracker("B"))
    ctx = make_context()
    if hook == "response":
        await p.run(ctx)
    else:
        tr = ToolResult(tool_call_id="t", name="tool", result="ok")
        await p.execute_tool_result(ctx, tr)
    assert order == expected


# ── Context Validation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_context_too_many_messages():
    from onion_core.pipeline import _MAX_MESSAGES
    p = Pipeline(provider=EchoProvider())
    ctx = AgentContext(messages=[Message(role="user", content="x")] * (_MAX_MESSAGES + 1))
    with pytest.raises(ValidationError, match="Too many messages"):
        await p.run(ctx)


@pytest.mark.asyncio
async def test_validate_context_content_too_long():
    p = Pipeline(provider=EchoProvider())
    ctx = AgentContext(messages=[Message(role="user", content="x" * 1_500_000)])
    with pytest.raises(ValidationError, match="content too long"):
        await p.run(ctx)


@pytest.mark.asyncio
async def test_validate_context_unicode_bomb():
    p = Pipeline(provider=EchoProvider())
    zalgo = "h" + "u\u0300\u0301\u0302\u0303\u0304" * 50 + "llo"
    ctx = AgentContext(messages=[Message(role="user", content=zalgo)])
    with pytest.raises(ValidationError, match="suspicious Unicode"):
        await p.run(ctx)


@pytest.mark.asyncio
async def test_validate_context_multimodal_content():
    from onion_core.models import ContentBlock
    p = Pipeline(provider=EchoProvider())
    blocks = [ContentBlock(type="text", text="hello")]
    ctx = AgentContext(messages=[Message(role="user", content=blocks)])
    resp = await p.run(ctx)
    assert isinstance(resp, LLMResponse)


# ── Runtime middleware registration ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_middleware_async():
    events: list[str] = []

    class AsyncMW(BaseMiddleware):
        async def startup(self):
            events.append("started")
        async def process_request(self, ctx):
            events.append("request")
            return ctx
        async def process_response(self, ctx, r):
            events.append("response")
            return r
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    p = Pipeline(provider=EchoProvider())
    await p.startup()
    await p.add_middleware_async(AsyncMW())
    ctx = make_context()
    resp = await p.run(ctx)
    assert isinstance(resp, LLMResponse)
    assert "started" in events
    assert "request" in events
    await p.shutdown()


# ── Sync API edge cases ──────────────────────────────────────────────────────

def test_run_async_in_sync_from_async_raises():
    async def _inner():
        p = Pipeline(provider=EchoProvider())
        with pytest.raises(RuntimeError, match="Cannot call sync methods"):
            p.run_sync(make_context())

    asyncio.run(_inner())


# ── Middleware error isolation chain ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_middleware_error_isolation_in_process_response():
    class BuggyMW(BaseMiddleware):
        async def process_request(self, ctx): return ctx
        async def process_response(self, ctx, r):
            raise RuntimeError("response error")
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    p = Pipeline(provider=EchoProvider()).add_middleware(BuggyMW())
    resp = await p.run(make_context())
    assert isinstance(resp, LLMResponse)


@pytest.mark.asyncio
async def test_mandatory_middleware_error_not_isolated():
    class MandatoryBuggyMW(BaseMiddleware):
        is_mandatory = True
        async def process_request(self, ctx): return ctx
        async def process_response(self, ctx, r):
            raise RuntimeError("mandatory failure")
        async def process_stream_chunk(self, ctx, c): return c
        async def on_tool_call(self, ctx, tc): return tc
        async def on_tool_result(self, ctx, r): return r
        async def on_error(self, ctx, e): pass

    p = Pipeline(provider=EchoProvider()).add_middleware(MandatoryBuggyMW())
    with pytest.raises(RuntimeError, match="mandatory"):
        await p.run(make_context())


# ── manager.py alias ─────────────────────────────────────────────────────────

def test_manager_alias():
    from onion_core.manager import MiddlewareManager
    assert MiddlewareManager is Pipeline


# ── from_config factory ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_from_config_creates_pipeline():
    from onion_core.config import ContextWindowConfig, OnionConfig, PipelineConfig, SafetyConfig
    cfg = OnionConfig(
        pipeline=PipelineConfig(max_retries=2),
        safety=SafetyConfig(enable_pii_masking=True),
        context_window=ContextWindowConfig(max_tokens=2000),
    )
    p = Pipeline.from_config(provider=EchoProvider(), config=cfg)
    assert len(p.middlewares) == 3
    resp = await p.run(make_context())
    assert isinstance(resp, LLMResponse)


# ── __init__.py imports ──────────────────────────────────────────────────────

def test_all_exports_importable():
    import onion_core
    for name in onion_core.__all__:
        assert hasattr(onion_core, name), f"Missing export: {name}"


# ── Tool call depth tracking ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_calls_depth_validation():
    """测试工具调用深度超过限制时抛出 ValidationError。"""
    from onion_core.models import FinishReason
    
    class DeepToolProvider(EchoProvider):
        async def complete(self, context):
            # 模拟返回带有工具调用的响应
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="t1", name="test_tool", arguments={})],
                finish_reason=FinishReason.TOOL_CALLS,
            )
    
    p = Pipeline(provider=DeepToolProvider())
    await p.startup()
    try:
        ctx = make_context()
        # 手动设置深度为 10（超过限制的阈值）
        ctx.metadata["tool_calls_depth"] = 11
        
        with pytest.raises(ValidationError, match="Tool call nesting depth exceeded"):
            await p.run(ctx)
    finally:
        await p.shutdown()
