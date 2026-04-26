from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tenacity import (
    AsyncRetrying,
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
    def __init__(self, message: str, retry_count: int, cause: Exception) -> None:
        super().__init__(message)
        self.retry_count = retry_count
        self.cause = cause


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, config: AgentConfig) -> None:
        self._registry = registry
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent_tools)

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
        except ExecutionError as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=str(e),
                retry_count=e.retry_count,
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

    async def _execute_with_retry(self, tool: BaseTool, kwargs: dict[str, Any]) -> tuple[Any, int]:
        max_attempts = self._config.tool_max_retries + 1
        attempt_number = 0

        def _before_sleep(retry_state: Any) -> None:
            logger.warning(
                "Retrying tool execution",
                extra={
                    "tool_name": tool.name,
                    "attempt": retry_state.attempt_number,
                    "elapsed": retry_state.seconds_since_start or 0.0,
                },
            )

        retrying = AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=0.5, max=10),
            retry=retry_if_exception_type((ToolTimeoutError, ToolError)),
            before_sleep=_before_sleep,
            reraise=True,
        )
        started = time.monotonic()

        try:
            async for attempt in retrying:
                attempt_number = attempt.retry_state.attempt_number
                with attempt:
                    try:
                        result = await asyncio.wait_for(
                            tool.execute(**kwargs),
                            timeout=self._config.tool_timeout_seconds,
                        )
                        return result, attempt_number - 1
                    except TimeoutError:
                        elapsed = time.monotonic() - started
                        logger.warning(
                            "Tool attempt timed out",
                            extra={
                                "tool_name": tool.name,
                                "attempt": attempt_number,
                                "elapsed": elapsed,
                            },
                        )
                        raise ToolTimeoutError(
                            f"Tool '{tool.name}' execution timed out after {self._config.tool_timeout_seconds}s"
                        ) from None
                    except ToolError:
                        elapsed = time.monotonic() - started
                        logger.warning(
                            "Tool attempt failed with business error",
                            extra={
                                "tool_name": tool.name,
                                "attempt": attempt_number,
                                "elapsed": elapsed,
                            },
                        )
                        raise
                    except Exception as e:
                        elapsed = time.monotonic() - started
                        logger.warning(
                            "Tool attempt failed with unexpected error",
                            extra={
                                "tool_name": tool.name,
                                "attempt": attempt_number,
                                "elapsed": elapsed,
                            },
                        )
                        raise ToolError(f"Tool '{tool.name}' execution failed: {e}") from e
        except ToolTimeoutError as e:
            raise ExecutionError(str(e), max(attempt_number - 1, 0), e) from e
        except ToolError as e:
            raise ExecutionError(str(e), max(attempt_number - 1, 0), e) from e

        raise ExecutionError("Tool execution ended unexpectedly", max(attempt_number - 1, 0), ToolError())
