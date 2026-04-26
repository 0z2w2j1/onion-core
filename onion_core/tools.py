"""
Onion Core - ToolRegistry（工具注册与执行器）

将 Python 函数注册为 Agent 可调用的工具，自动生成 JSON Schema，
并与 Pipeline 的 execute_tool_call / execute_tool_result 钩子集成。

用法：
    from onion_core.tools import ToolRegistry, tool

    registry = ToolRegistry()

    @registry.register
    async def web_search(query: str, max_results: int = 5) -> str:
        \"\"\"Search the web for information.\"\"\"
        return f"Results for: {query}"

    # 获取 OpenAI 格式的工具定义，注入 context.config
    context.config["tools"] = registry.to_openai_tools()

    # 执行 LLM 返回的工具调用
    for tc in response.tool_calls:
        intercepted = await pipeline.execute_tool_call(context, tc)
        result = await registry.execute(intercepted, context)
        processed = await pipeline.execute_tool_result(context, result)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypedDict, Union

from .models import _MAX_TOOL_CALL_DEPTH, AgentContext, ToolCall, ToolResult

logger = logging.getLogger("onion_core.tools")


class JsonSchemaProperty(TypedDict, total=False):
    type: str
    items: JsonSchemaProperty


class JsonSchema(TypedDict):
    type: str
    properties: dict[str, JsonSchemaProperty]
    required: list[str]


class OpenAIToolFunction(TypedDict):
    """OpenAI function schema inside tool definition."""
    name: str
    description: str
    parameters: JsonSchema


class OpenAIToolDefinition(TypedDict):
    """OpenAI tool definition with type and function wrapper."""
    type: str
    function: OpenAIToolFunction


class AnthropicToolInput(TypedDict):
    name: str
    description: str
    input_schema: JsonSchema


class ToolDefinition:
    """单个工具的元数据和执行函数。"""

    def __init__(self, func: Callable[..., Any], name: str | None = None, description: str | None = None) -> None:
        self.func = func
        self.name = name or func.__name__
        self.description = description or (inspect.getdoc(func) or "").strip()
        self._schema = self._build_schema()

    def _build_schema(self) -> JsonSchema:
        """从函数签名自动生成 JSON Schema，支持基础类型、Optional、List。"""
        sig = inspect.signature(self.func)
        properties: dict[str, JsonSchemaProperty] = {}
        required: list[str] = []

        def _ann_to_json_type(ann: Any) -> JsonSchemaProperty:
            """将 Python 类型注解转换为 JSON Schema 类型描述。"""
            _primitive: dict[type, JsonSchemaProperty] = {
                str: {"type": "string"},
                int: {"type": "integer"},
                float: {"type": "number"},
                bool: {"type": "boolean"},
                list: {"type": "array"},
                dict: {"type": "object"},
            }
            if ann in _primitive:
                return _primitive[ann]

            origin = getattr(ann, "__origin__", None)
            args = getattr(ann, "__args__", ())

            if origin is Union:
                non_none = [a for a in args if a is not type(None)]
                if non_none:
                    return _ann_to_json_type(non_none[0])
                return {"type": "string"}

            if origin is list:
                item_type = _ann_to_json_type(args[0]) if args else {"type": "string"}
                return {"type": "array", "items": item_type}

            if origin is dict:
                return {"type": "object"}

            return {"type": "string"}

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "context", "ctx"):
                continue
            ann = param.annotation
            schema_type = _ann_to_json_type(ann) if ann is not inspect.Parameter.empty else {"type": "string"}
            properties[param_name] = schema_type
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def to_openai_format(self) -> OpenAIToolDefinition:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._schema,
            },
        }

    def to_anthropic_format(self) -> AnthropicToolInput:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._schema,
        }


class ToolRegistry:
    """
    工具注册表。

    注册工具：
        @registry.register
        async def my_tool(arg: str) -> str: ...

        # 或手动注册
        registry.register_func(my_tool, name="custom_name")

    执行工具：
        result = await registry.execute(tool_call, context)

    幂等性支持：
        当 tool_call.idempotency_key 设置时，相同的 key 只执行一次，
        后续调用直接返回首次执行的结果。适用于网络重试导致工具被调用多次的场景。
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._idempotency_cache: dict[str, ToolResult] = {}

    def register(
        self,
        func: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Callable[..., Any]:
        """装饰器：注册工具函数。支持 @registry.register 和 @registry.register(name="x")。"""
        def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
            tool_def = ToolDefinition(f, name=name, description=description)
            self._tools[tool_def.name] = tool_def
            logger.info("Tool registered: %s", tool_def.name)
            return f

        if func is not None:
            return decorator(func)
        return decorator

    def register_func(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> ToolRegistry:
        """手动注册工具函数，支持链式调用。"""
        tool_def = ToolDefinition(func, name=name, description=description)
        self._tools[tool_def.name] = tool_def
        logger.info("Tool registered: %s", tool_def.name)
        return self

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def to_openai_tools(self) -> list[OpenAIToolDefinition]:
        """生成 OpenAI function calling 格式的工具列表。"""
        return [t.to_openai_format() for t in self._tools.values()]

    def to_anthropic_tools(self) -> list[AnthropicToolInput]:
        """生成 Anthropic tool_use 格式的工具列表。"""
        return [t.to_anthropic_format() for t in self._tools.values()]

    def clear_idempotency_cache(self) -> None:
        self._idempotency_cache.clear()

    async def execute(
        self,
        tool_call: ToolCall,
        context: AgentContext | None = None,
    ) -> ToolResult:
        """
        执行工具调用，返回 ToolResult。

        若工具函数接受 `context` 参数，会自动注入 AgentContext。
        同步函数会在线程池中执行，不阻塞事件循环。

        幂等性：当 tool_call.idempotency_key 设置时，相同 key 的结果会被缓存，
        避免幂等操作失败重试时的副作用。
        """
        tool_def = self._tools.get(tool_call.name)
        if tool_def is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                error=f"Tool '{tool_call.name}' not found in registry",
            )

        if tool_call.idempotency_key is not None:
            cached = self._idempotency_cache.get(tool_call.idempotency_key)
            if cached is not None:
                logger.info("Idempotency hit for key='%s', returning cached result", tool_call.idempotency_key)
                return cached.model_copy(deep=True)

        if context and context.metadata.get("tool_calls_depth", 0) > _MAX_TOOL_CALL_DEPTH:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                error=f"Tool call nesting depth exceeded: {context.metadata.get('tool_calls_depth', 0)} > {_MAX_TOOL_CALL_DEPTH}",
            )

        try:
            sig = inspect.signature(tool_def.func)
            kwargs = dict(tool_call.arguments)

            # 注入 context（若函数签名中有 context 或 ctx 参数）
            if "context" in sig.parameters and context is not None:
                kwargs["context"] = context
            elif "ctx" in sig.parameters and context is not None:
                kwargs["ctx"] = context

            # 基础参数校验：检查必填参数是否都已提供
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "context", "ctx"):
                    continue
                if (param.default is inspect.Parameter.empty
                        and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                        and param_name not in kwargs):
                    return ToolResult(
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        result=None,
                        error=f"Missing required argument '{param_name}' for tool '{tool_call.name}'",
                    )

            if asyncio.iscoroutinefunction(tool_def.func):
                result = await tool_def.func(**kwargs)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: tool_def.func(**kwargs))

            logger.info("Tool '%s' executed successfully.", tool_call.name)
            # 统一转为 str 以满足 Pydantic Union[str, Dict, List] 类型约束
            if not isinstance(result, (str, dict, list)):
                result = str(result)
            
            # 截断过大的工具结果
            max_chars = context.config.get("tool_result_max_chars", 50000) if context else 50000
            if isinstance(result, str) and len(result) > max_chars:
                logger.warning(
                    "Tool '%s' result truncated: %d > %d chars",
                    tool_call.name, len(result), max_chars,
                )
                result = result[:max_chars] + "...[truncated]"
            
            tool_result = ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=result,
            )
            if tool_call.idempotency_key is not None:
                self._idempotency_cache[tool_call.idempotency_key] = tool_result
                if len(self._idempotency_cache) > 10000:
                    oldest = next(iter(self._idempotency_cache))
                    del self._idempotency_cache[oldest]
            return tool_result
        except Exception as exc:
            logger.error("Tool '%s' raised %s: %s", tool_call.name, type(exc).__name__, exc)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                error=f"{type(exc).__name__}: {exc}",
            )
