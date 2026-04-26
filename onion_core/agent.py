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

import hashlib
import json
import logging
from collections import deque

from .models import AgentContext, LLMResponse, Message, ToolCall, ToolResult
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
        registry: ToolRegistry | None = None,
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
        last_response: LLMResponse | None = None
        dedup_policy = self._get_tool_call_dedup_policy(context)
        progress_window = self._get_progress_window(context)
        recent_state_hashes: deque[str] = deque(maxlen=progress_window)

        for turn in range(self._max_turns):
            response = await self._pipeline.run(context)
            last_response = response

            if not response.has_tool_calls:
                logger.info("AgentLoop finished in %d turn(s).", turn + 1)
                return response

            logger.info("Turn %d: %d tool call(s).", turn + 1, len(response.tool_calls))

            turn_seen_ids: set[str] = set()
            turn_seen_signatures: set[str] = set()
            turn_result_summaries: list[str] = []

            # 执行所有工具调用
            for tool_call in response.tool_calls:
                call_signature = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True)}"
                if self._is_duplicate_tool_call(
                    tool_call,
                    call_signature,
                    dedup_policy,
                    turn_seen_ids,
                    turn_seen_signatures,
                ):
                    logger.warning(
                        "[%s] Duplicate tool call skipped by policy=%s: id=%s, signature=%s",
                        context.request_id,
                        dedup_policy,
                        tool_call.id,
                        call_signature,
                    )
                    continue

                # 通过 pipeline 拦截（安全检查、审计）
                intercepted = await self._pipeline.execute_tool_call(context, tool_call)

                # 执行工具
                tool_result = await self._registry.execute(intercepted, context)

                # 通过 pipeline 处理结果（PII 脱敏等）
                processed = await self._pipeline.execute_tool_result(context, tool_result)
                turn_result_summaries.append(self._summarize_tool_result(processed))

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

            turn_state_hash = self._build_turn_state_hash(response, turn_result_summaries)
            recent_state_hashes.append(turn_state_hash)
            if (
                progress_window > 0
                and len(recent_state_hashes) == progress_window
                and len(set(recent_state_hashes)) == 1
            ):
                logger.warning(
                    "[%s] No state progress detected for %d turns; stopping to prevent infinite loop.",
                    context.request_id,
                    progress_window,
                )
                return last_response

        # 达到最大轮次
        logger.warning("AgentLoop reached max_turns=%d without stop.", self._max_turns)
        if self._raise_on_max_turns:
            raise AgentLoopError(
                f"Agent loop exceeded max_turns={self._max_turns} without a final response."
            )
        return last_response  # type: ignore[return-value]

    @staticmethod
    def _get_tool_call_dedup_policy(context: AgentContext) -> str:
        pipeline_cfg = context.config.get("onion", {}).get("pipeline", {})
        policy = context.config.get("tool_call_dedup_policy", pipeline_cfg.get("tool_call_dedup_policy", "relaxed"))
        if policy not in {"strict", "relaxed", "off"}:
            return "relaxed"
        return policy

    @staticmethod
    def _get_progress_window(context: AgentContext) -> int:
        pipeline_cfg = context.config.get("onion", {}).get("pipeline", {})
        window = context.config.get("agent_progress_window", pipeline_cfg.get("agent_progress_window", 3))
        try:
            parsed = int(window)
        except (TypeError, ValueError):
            return 3
        return max(parsed, 0)

    @staticmethod
    def _is_duplicate_tool_call(
        tool_call: ToolCall,
        call_signature: str,
        policy: str,
        turn_seen_ids: set[str],
        turn_seen_signatures: set[str],
    ) -> bool:
        if policy == "off":
            return False

        duplicate = tool_call.id in turn_seen_ids
        if policy == "strict":
            duplicate = duplicate or call_signature in turn_seen_signatures

        turn_seen_ids.add(tool_call.id)
        turn_seen_signatures.add(call_signature)
        return duplicate

    @staticmethod
    def _summarize_tool_result(result: ToolResult) -> str:
        payload = {
            "id": result.tool_call_id,
            "name": result.name,
            "error": result.error,
            "result": result.result,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_turn_state_hash(response: LLMResponse, tool_result_summaries: list[str]) -> str:
        payload = {
            "finish_reason": response.finish_reason,
            "content": response.content,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": c.arguments}
                for c in response.tool_calls
            ],
            "tool_results": tool_result_summaries,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
