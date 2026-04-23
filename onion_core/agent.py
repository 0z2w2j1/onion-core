"""
Onion Core - AgentLoop

多轮工具调用编排原语，封装 while-tool_calls 循环，
避免每个消费者重复实现相同的逻辑。

用法：
    from onion_core.agent import AgentLoop

    loop = AgentLoop(pipeline=pipeline, registry=registry, max_turns=10)
    response = await loop.run(context)
    print(response.content)
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import AgentContext, LLMResponse, Message
from .pipeline import Pipeline
from .tools import ToolRegistry

logger = logging.getLogger("onion_core.agent")


class AgentLoopError(Exception):
    """Agent 循环异常（超出最大轮次等）。"""


class AgentLoop:
    """
    多轮工具调用编排器。

    自动处理：
      1. pipeline.run(context)
      2. 若 response.has_tool_calls → 通过 pipeline 拦截 → registry.execute → 追加消息
      3. 重复直到 finish_reason == "stop" 或达到 max_turns

    示例：
        loop = AgentLoop(pipeline=pipeline, registry=registry)
        final = await loop.run(AgentContext(messages=[Message(role="user", content="...")]))
        print(final.content)
    """

    def __init__(
        self,
        pipeline: Pipeline,
        registry: Optional[ToolRegistry] = None,
        max_turns: int = 10,
        raise_on_max_turns: bool = False,
    ) -> None:
        self._pipeline = pipeline
        self._registry = registry or ToolRegistry()
        self._max_turns = max_turns
        self._raise_on_max_turns = raise_on_max_turns

    async def run(self, context: AgentContext) -> LLMResponse:
        """
        执行 Agent 循环直到 LLM 返回最终文本或达到最大轮次。

        Returns:
            最终的 LLMResponse（finish_reason="stop"）
        """
        last_response: Optional[LLMResponse] = None

        for turn in range(self._max_turns):
            response = await self._pipeline.run(context)
            last_response = response

            if not response.has_tool_calls:
                logger.info("AgentLoop finished in %d turn(s).", turn + 1)
                return response

            logger.info("Turn %d: %d tool call(s).", turn + 1, len(response.tool_calls))

            # 执行所有工具调用
            for tool_call in response.tool_calls:
                # 通过 pipeline 拦截（安全检查、审计）
                intercepted = await self._pipeline.execute_tool_call(context, tool_call)

                # 执行工具
                tool_result = await self._registry.execute(intercepted, context)

                # 通过 pipeline 处理结果（PII 脱敏等）
                processed = await self._pipeline.execute_tool_result(context, tool_result)

                # 追加工具结果到对话历史
                result_text = (
                    str(processed.result) if not processed.is_error
                    else f"Error: {processed.error}"
                )
                context.messages.append(Message(
                    role="tool",
                    content=result_text,
                    name=processed.name,
                ))

            # 若 LLM 同时返回了文本内容，也追加到历史
            if response.content:
                context.messages.append(
                    Message(role="assistant", content=response.content)
                )

        # 达到最大轮次
        logger.warning("AgentLoop reached max_turns=%d without stop.", self._max_turns)
        if self._raise_on_max_turns:
            raise AgentLoopError(
                f"Agent loop exceeded max_turns={self._max_turns} without a final response."
            )
        return last_response  # type: ignore[return-value]
