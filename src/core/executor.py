from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.schema.models import (
    AgentConfig,
    ToolCall,
    ToolResult,
)
from src.tools.base import BaseTool, ToolError, ToolTimeoutError, ToolValidationError
from src.tools.registry import ToolNotFoundError, ToolRegistry

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    pass


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, config: AgentConfig) -> None:
        self._registry = registry
        self._config = config
        self._semaphore = asyncio.Semaphore(5)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        start = time.monotonic()
        retry_count = 0

        try:
            tool = self._registry.get(tool_call.name)
        except ToolNotFoundError as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )

        try:
            validated = tool.validate_args(tool_call.arguments)
        except ToolValidationError as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )

        try:
            result, retry_count = await self._execute_with_retry(
                tool,
                validated.model_dump(),
            )
        except RetryError as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=f"All retries exhausted: {e}",
                retry_count=self._config.tool_max_retries,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except TimeoutError:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=f"Tool execution timed out after {self._config.tool_timeout_seconds}s",
                retry_count=retry_count,
                duration_ms=(time.monotonic() - start) * 1000,
            )

        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            result=result,
            retry_count=retry_count,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def execute_all(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        if not tool_calls:
            return []

        async def _execute_one(tc: ToolCall) -> ToolResult:
            async with self._semaphore:
                return await self.execute(tc)

        tasks = [_execute_one(tc) for tc in tool_calls]
        return await asyncio.gather(*tasks)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=0.5, max=10),
        retry=retry_if_exception_type((ToolTimeoutError, ToolError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _execute_with_retry(self, tool: BaseTool, kwargs: dict[str, Any]) -> tuple[Any, int]:
        try:
            result = await asyncio.wait_for(
                tool.execute(**kwargs),
                timeout=self._config.tool_timeout_seconds,
            )
            return result, 0
        except TimeoutError:
            raise ToolTimeoutError(
                f"Tool '{tool.name}' execution timed out after {self._config.tool_timeout_seconds}s"
            ) from None
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Tool '{tool.name}' execution failed: {e}") from e
