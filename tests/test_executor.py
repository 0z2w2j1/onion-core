from __future__ import annotations

import asyncio
import logging

import pytest
from pydantic import BaseModel

from src.core.executor import ToolExecutor
from src.schema.models import AgentConfig, ToolCall
from src.tools.base import BaseTool, ToolError
from src.tools.registry import ToolRegistry


class EmptyArgs(BaseModel):
    pass


class FlakyTool(BaseTool):
    name = "flaky_tool"
    description = "Flaky tool for retry tests"
    input_schema = EmptyArgs

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.calls = 0

    async def execute(self, **kwargs):  # type: ignore[override]
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ToolError("transient failure")
        return "ok"


class TimeoutTool(BaseTool):
    name = "timeout_tool"
    description = "Timeout tool for retry tests"
    input_schema = EmptyArgs

    async def execute(self, **kwargs):  # type: ignore[override]
        await asyncio.sleep(2.0)
        return "late"


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
    registry = ToolRegistry()
    tool = FlakyTool(fail_times=fail_times)
    registry.register(tool)

    executor = ToolExecutor(
        registry,
        AgentConfig(tool_max_retries=tool_max_retries, tool_timeout_seconds=1.0),
    )

    result = await executor.execute(ToolCall(id="call_1", name=tool.name, arguments={}))

    assert result.is_error is is_error
    assert result.retry_count == retry_count
    assert tool.calls == call_count


@pytest.mark.asyncio
async def test_tool_executor_timeout_error_and_retry_logging_fields(caplog: pytest.LogCaptureFixture):
    registry = ToolRegistry()
    tool = TimeoutTool()
    registry.register(tool)

    executor = ToolExecutor(
        registry,
        AgentConfig(tool_max_retries=1, tool_timeout_seconds=1.0),
    )

    with caplog.at_level(logging.WARNING, logger="src.core.executor"):
        result = await executor.execute(ToolCall(id="call_1", name=tool.name, arguments={}))

    assert result.is_error
    assert "timed out" in (result.error or "")
    assert result.retry_count == 1

    timeout_records = [r for r in caplog.records if r.message == "Tool attempt timed out"]
    assert len(timeout_records) == 2
    for record in timeout_records:
        assert getattr(record, "tool_name", None) == tool.name
        assert getattr(record, "attempt", None) in {1, 2}
        assert isinstance(getattr(record, "elapsed", None), float)
