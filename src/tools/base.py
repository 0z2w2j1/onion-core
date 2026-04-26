from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolError(Exception):
    pass


class ToolTimeoutError(ToolError):
    pass


class ToolValidationError(ToolError):
    pass


class BaseTool(ABC):
    name: str
    description: str
    input_schema: type[BaseModel]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "name") or not cls.name:
            raise TypeError(f"Tool {cls.__name__} must define 'name' class attribute")
        if not hasattr(cls, "description") or not cls.description:
            raise TypeError(f"Tool {cls.__name__} must define 'description' class attribute")
        if not hasattr(cls, "input_schema"):
            raise TypeError(
                f"Tool {cls.__name__} must define 'input_schema' as a Pydantic BaseModel"
            )

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        ...

    def validate_args(self, arguments: dict[str, Any]) -> BaseModel:
        try:
            return self.input_schema(**arguments)
        except Exception as e:
            raise ToolValidationError(
                f"Tool '{self.name}' argument validation failed: {e}"
            ) from e

    def to_openai_schema(self) -> dict[str, Any]:
        schema = self.input_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        schema = self.input_schema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        }
