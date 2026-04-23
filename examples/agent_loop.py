"""
Onion Core - Agent 循环集成示例

展示完整的多轮工具调用循环：
  1. 用户输入 → Pipeline.run()
  2. LLM 返回 tool_calls → ToolRegistry.execute()
  3. 工具结果追加到 messages → 再次调用 LLM
  4. LLM 返回最终文本回复

运行：
    python examples/agent_loop.py
"""

from __future__ import annotations

import ast
import asyncio
import logging
import sys

sys.path.insert(0, ".")

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    SafetyGuardrailMiddleware,
)
from onion_core.observability import configure_logging
from onion_core.tools import ToolRegistry

configure_logging(level="INFO", json_format=False)
logger = logging.getLogger("example.agent_loop")

# ── 工具定义 ─────────────────────────────────────────────────────────────────

registry = ToolRegistry()


@registry.register
async def get_weather(city: str) -> str:
    return f"Weather in {city}: 22°C, partly cloudy"


@registry.register
async def calculate(expression: str) -> str:
    try:
        allowed = set("0123456789+-*/()., ")
        if not all(c in allowed for c in expression):
            return "Error: invalid characters in expression"
        result = ast.literal_eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


# ── 模拟 LLM（带工具调用）────────────────────────────────────────────────────

class ToolAwareEchoProvider(EchoProvider):
    def __init__(self):
        super().__init__()
        self._call_count = 0

    async def complete(self, context: AgentContext):
        from onion_core.models import LLMResponse, ToolCall
        self._call_count += 1

        if self._call_count == 1:
            last_user = next(
                (m.content for m in reversed(context.messages) if m.role == "user"), ""
            )
            if "weather" in last_user.lower():
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(id="tc_001", name="get_weather", arguments={"city": "Beijing"})],
                    finish_reason="tool_calls",
                    model="mock-tool-llm",
                )
            elif "calculate" in last_user.lower() or any(c.isdigit() for c in last_user):
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(id="tc_002", name="calculate", arguments={"expression": "2 + 2 * 3"})],
                    finish_reason="tool_calls",
                    model="mock-tool-llm",
                )

        tool_results = [m for m in context.messages if m.role == "tool"]
        if tool_results:
            return LLMResponse(
                content=f"Based on the tool results: {tool_results[-1].content}",
                finish_reason="stop",
                model="mock-tool-llm",
            )

        return LLMResponse(
            content="I can help you with weather and calculations!",
            finish_reason="stop",
            model="mock-tool-llm",
        )


# ── Agent 循环 ────────────────────────────────────────────────────────────────

async def run_agent(pipeline: Pipeline, user_input: str, max_turns: int = 5) -> str:
    context = AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant with access to tools."),
            Message(role="user", content=user_input),
        ],
        config={"tools": registry.to_openai_tools()},
    )

    for turn in range(max_turns):
        logger.info("Turn %d | messages=%d", turn + 1, len(context.messages))
        response = await pipeline.run(context)

        if response.finish_reason == "stop" or not response.has_tool_calls:
            return response.content or ""

        for tool_call in response.tool_calls:
            logger.info("Executing tool: %s(%s)", tool_call.name, tool_call.arguments)
            intercepted = await pipeline.execute_tool_call(context, tool_call)
            tool_result = await registry.execute(intercepted, context)
            processed_result = await pipeline.execute_tool_result(context, tool_result)

            result_content = str(processed_result.result) if not processed_result.is_error else f"Error: {processed_result.error}"
            context.messages.append(Message(
                role="tool",
                content=result_content,
                name=processed_result.name,
            ))

        if response.content:
            context.messages.append(Message(role="assistant", content=response.content))

    logger.warning("Max turns (%d) reached without final response.", max_turns)
    return "Max tool call turns reached."


# ── 主程序 ────────────────────────────────────────────────────────────────────

async def main():
    async with Pipeline(
        provider=ToolAwareEchoProvider(),
        provider_timeout=10.0,
        max_retries=1,
    ) as pipeline:
        pipeline.add_middleware(ObservabilityMiddleware())
        pipeline.add_middleware(RateLimitMiddleware(max_requests=100, window_seconds=60))
        pipeline.add_middleware(SafetyGuardrailMiddleware())
        pipeline.add_middleware(ContextWindowMiddleware(max_tokens=4000))

        test_cases = [
            "What's the weather in Beijing?",
            "Calculate 2 + 2 * 3 for me",
            "Just say hello",
        ]

        for user_input in test_cases:
            print(f"\n{'─'*50}")
            print(f"User: {user_input}")
            result = await run_agent(pipeline, user_input)
            print(f"Agent: {result}")

    print(f"\n{'─'*50}")
    print("Available tools:", registry.tool_names)


if __name__ == "__main__":
    asyncio.run(main())
