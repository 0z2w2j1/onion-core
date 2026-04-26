from __future__ import annotations

import logging
from typing import Any

from src.tools.base import BaseTool, ToolError

logger = logging.getLogger(__name__)


class ToolNotFoundError(ToolError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            logger.warning("Tool '%s' already registered, overwriting.", tool.name)
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def register_many(self, tools: list[BaseTool]) -> None:
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> BaseTool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{name}' not found in registry. Available: {self.list_names()}")
        return tool

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def to_openai_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def to_anthropic_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_anthropic_schema() for tool in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __bool__(self) -> bool:
        return len(self._tools) > 0
