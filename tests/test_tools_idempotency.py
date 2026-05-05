"""ToolRegistry idempotency semantics: cache hit, in-flight concurrent merge, failure cleanup."""

from __future__ import annotations

import asyncio

import pytest

from onion_core.models import ToolCall
from onion_core.tools import ToolRegistry


@pytest.mark.asyncio
async def test_idempotency_cache_hit_returns_cached_result():
    registry = ToolRegistry()
    call_count = 0

    @registry.register
    async def do_work(x: int) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{x}"

    tc = ToolCall(id="t1", name="do_work", arguments={"x": 1}, idempotency_key="k1")

    r1 = await registry.execute(tc)
    r2 = await registry.execute(tc)

    assert call_count == 1
    assert r1.result == r2.result == "result-1"


@pytest.mark.asyncio
async def test_idempotency_concurrent_calls_share_single_execution():
    """Regression: concurrent tool calls with the same idempotency_key must
    not double-execute. They should join the in-flight future."""
    registry = ToolRegistry()
    call_count = 0
    gate = asyncio.Event()

    @registry.register
    async def slow_work(x: int) -> str:
        nonlocal call_count
        call_count += 1
        await gate.wait()
        return f"result-{x}"

    tc = ToolCall(id="t1", name="slow_work", arguments={"x": 1}, idempotency_key="same-key")

    tasks = [asyncio.create_task(registry.execute(tc)) for _ in range(5)]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*tasks)

    assert call_count == 1
    assert all(r.result == "result-1" for r in results)
    assert all(r.error is None for r in results)


@pytest.mark.asyncio
async def test_idempotency_failure_is_not_cached():
    """Failed tool results (with error set) must not be cached — next call
    with same key should re-execute."""
    registry = ToolRegistry()
    call_count = 0

    @registry.register
    async def flaky(x: int) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        return f"ok-{x}"

    tc = ToolCall(id="t1", name="flaky", arguments={"x": 1}, idempotency_key="k-fail")

    r1 = await registry.execute(tc)
    assert r1.error is not None

    r2 = await registry.execute(tc)
    assert r2.error is None
    assert r2.result == "ok-1"
    assert call_count == 2


@pytest.mark.asyncio
async def test_idempotency_concurrent_with_failure_releases_in_flight():
    """If the shared execution raises, joiners see the same failed ToolResult
    and subsequent calls can retry."""
    registry = ToolRegistry()
    call_count = 0
    gate = asyncio.Event()

    @registry.register
    async def boom(x: int) -> str:
        nonlocal call_count
        call_count += 1
        await gate.wait()
        raise ValueError("nope")

    tc = ToolCall(id="t1", name="boom", arguments={"x": 1}, idempotency_key="k-boom")

    tasks = [asyncio.create_task(registry.execute(tc)) for _ in range(3)]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*tasks)

    assert call_count == 1
    assert all(r.error is not None and "nope" in r.error for r in results)

    r_retry = await registry.execute(tc)
    assert r_retry.error is not None
    assert call_count == 2


@pytest.mark.asyncio
async def test_no_idempotency_key_always_executes():
    registry = ToolRegistry()
    call_count = 0

    @registry.register
    async def do_work(x: int) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{x}"

    tc = ToolCall(id="t1", name="do_work", arguments={"x": 1})

    await registry.execute(tc)
    await registry.execute(tc)
    assert call_count == 2
