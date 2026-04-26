from __future__ import annotations

import asyncio
import logging

import pytest

from onion_core.agent import ToolExecutor
from onion_core.models import AgentConfig, ToolCall
from onion_core.tools import ToolRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_max_retries", "fail_times", "is_error", "retry_count", "call_count"),
    [
        (0, 1, True, 0, 1),
        (1, 1, False, 1, 2),
        (2, 2, False, 2, 3),
    ],
)
async def test_tool_executor_retry_boundaries(
    tool_max_retries: int,
    fail_times: int,
    is_error: bool,
    retry_count: int,
    call_count: int,
):
    call_counter = {"calls": 0}

    async def flaky_tool() -> str:
        call_counter["calls"] += 1
        if call_counter["calls"] <= fail_times:
            raise ValueError("transient failure")
        return "ok"

    registry = ToolRegistry()
    registry.register_func(flaky_tool, name="flaky_tool")

    executor = ToolExecutor(
        registry,
        AgentConfig(tool_max_retries=tool_max_retries, tool_timeout_seconds=1.0),
    )

    result = await executor.execute(ToolCall(id="call_1", name="flaky_tool", arguments={}))

    assert result.is_error is is_error
    assert result.retry_count == retry_count
    assert call_counter["calls"] == call_count


@pytest.mark.asyncio
async def test_tool_executor_timeout_error_and_retry_logging_fields(caplog: pytest.LogCaptureFixture):
    async def slow_tool() -> str:
        await asyncio.sleep(2.0)
        return "late"

    registry = ToolRegistry()
    registry.register_func(slow_tool, name="slow_tool")

    executor = ToolExecutor(
        registry,
        AgentConfig(tool_max_retries=1, tool_timeout_seconds=1.0),
    )

    with caplog.at_level(logging.WARNING, logger="onion_core.agent"):
        result = await executor.execute(ToolCall(id="call_1", name="slow_tool", arguments={}))

    assert result.is_error
    assert "timed out" in (result.error or "")
    assert result.retry_count == 1

    timeout_records = [r for r in caplog.records if "timed out" in r.message]
    assert len(timeout_records) == 1
