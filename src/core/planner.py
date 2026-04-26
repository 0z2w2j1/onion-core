from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.core.state import AgentState
from src.schema.models import ActionType, AgentConfig, AgentStatus, LLMResponse


@dataclass(frozen=True)
class PlannerDecision:
    action_type: ActionType
    reasoning: str
    metadata: dict[str, object] = field(default_factory=dict)


class BasePlanner(ABC):
    @abstractmethod
    async def decide(self, state: AgentState, llm_response: LLMResponse | None) -> PlannerDecision:
        ...


class DefaultPlanner(BasePlanner):
    def __init__(self, config: AgentConfig) -> None:
        self._config = config

    async def decide(self, state: AgentState, llm_response: LLMResponse | None) -> PlannerDecision:
        if state.status == AgentStatus.ERROR or state.status == AgentStatus.CANCELLED:
            return PlannerDecision(
                action_type=ActionType.ERROR,
                reasoning="Agent is in terminal error/cancelled state",
                metadata={"status": state.status.value},
            )

        if state.steps >= self._config.max_steps:
            return PlannerDecision(
                action_type=ActionType.FINISH,
                reasoning=f"Reached max_steps limit ({self._config.max_steps})",
                metadata={"max_steps_reached": True},
            )

        if llm_response is None:
            return PlannerDecision(
                action_type=ActionType.REASON,
                reasoning="No LLM response yet, need to reason first",
                metadata={},
            )

        if llm_response.has_tool_calls:
            return PlannerDecision(
                action_type=ActionType.ACT,
                reasoning=f"LLM requested {len(llm_response.tool_calls)} tool call(s)",
                metadata={"tool_count": len(llm_response.tool_calls)},
            )

        if llm_response.is_finished:
            return PlannerDecision(
                action_type=ActionType.FINISH,
                reasoning=f"LLM finished with reason: {llm_response.finish_reason.value}",
                metadata={"finish_reason": llm_response.finish_reason.value},
            )

        return PlannerDecision(
            action_type=ActionType.REASON,
            reasoning="Continue reasoning loop",
            metadata={},
        )
