from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import httpx

from src.schema.models import AgentConfig, LLMResponse, Message

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMAuthenticationError(LLMError):
    pass


class BaseLLMClient(ABC):
    def __init__(self, config: AgentConfig):
        self._config = config
        self._client: httpx.AsyncClient | None = None

    @abstractmethod
    async def complete(self, messages: list[Message]) -> LLMResponse:
        ...

    @abstractmethod
    def stream(self, messages: list[Message]) -> AsyncIterator[dict[str, Any]]:
        ...

    @abstractmethod
    async def _build_payload(self, messages: list[Message]) -> dict[str, Any]:
        ...

    @abstractmethod
    def _parse_response(self, payload: dict[str, Any]) -> LLMResponse:
        ...

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = self._create_client()
        return self._client

    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(self._config.max_tokens / 10 + 30),
                write=10.0,
                pool=10.0,
            ),
            limits=httpx.Limits(
                max_keepalive_connections=self._config.llm_max_keepalive,
                max_connections=self._config.llm_max_connections,
                keepalive_expiry=30.0,
            ),
            headers=self._default_headers(),
        )

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> BaseLLMClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @staticmethod
    def _extract_api_error(response: httpx.Response) -> str:
        try:
            body = response.json()
            msg: object = body.get("error", {}).get("message", response.text)
            return str(msg)
        except Exception:
            return str(response.text)
