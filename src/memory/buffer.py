from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.schema.models import AgentConfig, Message, MessageRole

logger = logging.getLogger(__name__)


class MemorySummarizer(ABC):
    @abstractmethod
    async def summarize(self, messages: list[Message]) -> str:
        ...


class SlidingWindowMemory:
    def __init__(
        self,
        config: AgentConfig,
        summarizer: MemorySummarizer | None = None,
    ) -> None:
        self._max_tokens = config.memory_max_tokens
        self._summarizer = summarizer
        self._token_counter = TokenEstimator()

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        if value < 256:
            raise ValueError("max_tokens must be at least 256")
        self._max_tokens = value

    def trim(self, messages: list[Message]) -> list[Message]:
        if not messages:
            return []

        total = self._token_counter.estimate_tokens(messages)
        if total <= self._max_tokens:
            return messages

        logger.info(
            "Trimming messages: %d tokens exceeds limit of %d",
            total,
            self._max_tokens,
        )

        system_messages: list[Message] = []
        non_system: list[Message] = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                system_messages.append(m)
            else:
                non_system.append(m)

        system_reserve = self._token_counter.estimate_tokens(system_messages)
        available = self._max_tokens - system_reserve

        if available <= 0:
            logger.error(
                "System messages alone (%d tokens) exceed memory limit (%d tokens)",
                system_reserve,
                self._max_tokens,
            )
            recent_non_system = non_system[-1:]
            return system_messages[:-max(1, len(system_messages) - 1)] + recent_non_system

        kept: list[Message] = []
        running_tokens = 0

        for m in reversed(non_system):
            msg_tokens = self._token_counter.estimate_tokens([m])
            if running_tokens + msg_tokens > available:
                break
            kept.append(m)
            running_tokens += msg_tokens

        kept.reverse()

        result = system_messages + kept
        final_tokens = self._token_counter.estimate_tokens(result)
        logger.info(
            "Trimmed from %d to %d messages (%d -> %d tokens)",
            len(messages),
            len(result),
            total,
            final_tokens,
        )
        return result

    async def trim_with_summary(self, messages: list[Message]) -> list[Message]:
        if not self._summarizer:
            return self.trim(messages)

        total = self._token_counter.estimate_tokens(messages)
        if total <= self._max_tokens:
            return messages

        system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
        non_system = [m for m in messages if m.role != MessageRole.SYSTEM]

        if len(non_system) <= 4:
            return self.trim(messages)

        boundary = max(1, len(non_system) // 3)
        to_summarize = non_system[:boundary]
        recent = non_system[boundary:]

        try:
            summary_text = await self._summarizer.summarize(to_summarize)
            summary_msg = Message(role=MessageRole.SYSTEM, content=f"[Conversation Summary]\n{summary_text}")
            merged = system_messages + [summary_msg] + recent
            return self.trim(merged)
        except Exception as e:
            logger.warning("Summarization failed, falling back to trim: %s", e)
            return self.trim(messages)

    def get_token_estimate(self, messages: list[Message]) -> int:
        return self._token_counter.estimate_tokens(messages)


class TokenEstimator:
    AVERAGE_CHARS_PER_TOKEN = 4.0

    def estimate_tokens(self, messages: list[Message]) -> int:
        total: float = 0.0
        for m in messages:
            total += 4
            if m.name:
                total += 1
            content = m.content or ""
            total += len(content) / self.AVERAGE_CHARS_PER_TOKEN
        return max(1, int(total))
