from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.llm.base import (
    BaseLLMClient,
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from src.schema.models import (
    AgentConfig,
    FinishReason,
    LLMResponse,
    Message,
    ToolCall,
    UsageStats,
)

logger = logging.getLogger(__name__)

_SINGLETON_CLIENTS: dict[str, OpenAILLMClient] = {}


class OpenAILLMClient(BaseLLMClient):
    BASE_URL = "https://api.openai.com/v1"

    def __init__(self, config: AgentConfig, api_key: str | None = None, base_url: str | None = None):
        super().__init__(config)
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = (base_url or os.environ.get("OPENAI_BASE_URL", self.BASE_URL)).rstrip("/")
        if not self._api_key:
            raise LLMAuthenticationError(
                "OpenAI API key not found. Set OPENAI_API_KEY environment variable."
            )

    @classmethod
    def get_instance(
        cls,
        config: AgentConfig,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_key: str | None = None,
    ) -> OpenAILLMClient:
        key = cache_key or (api_key or "") + (base_url or "")
        if key not in _SINGLETON_CLIENTS:
            _SINGLETON_CLIENTS[key] = cls(config=config, api_key=api_key, base_url=base_url)
        return _SINGLETON_CLIENTS[key]

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    async def complete(self, messages: list[Message]) -> LLMResponse:
        payload = await self._build_payload(messages)
        client = await self.get_client()
        url = f"{self._base_url}/chat/completions"
        start = time.monotonic()

        try:
            response = await self._make_request_with_retry(client, url, payload)
        except RetryError as e:
            raise LLMError(f"All retries exhausted for LLM request: {e}") from e

        latency_ms = (time.monotonic() - start) * 1000
        result = self._parse_response(response)
        result.latency_ms = latency_ms
        return result

    def stream(self, messages: list[Message]) -> AsyncIterator[dict[str, Any]]:
        return self._stream_impl(messages)

    async def _stream_impl(self, messages: list[Message]) -> AsyncIterator[dict[str, Any]]:
        payload = await self._build_payload(messages)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

        client = await self.get_client()
        url = f"{self._base_url}/chat/completions"

        try:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    error_msg = self._extract_api_error_from_bytes(error_text)
                    raise LLMError(
                        f"OpenAI stream error ({response.status_code}): {error_msg}"
                    )
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk: dict[str, Any] = json.loads(data_str)
                        yield chunk
                    except json.JSONDecodeError:
                        continue
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"OpenAI stream timed out: {e}") from e

    async def _build_payload(self, messages: list[Message]) -> dict[str, Any]:
        formatted: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role.value}
            if m.content is not None:
                msg["content"] = m.content
            if m.name:
                msg["name"] = m.name
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            formatted.append(msg)

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": formatted,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "max_tokens": self._config.max_tokens,
        }
        if self._config.stop_sequences:
            payload["stop"] = list(self._config.stop_sequences)
        return payload

    def _parse_response(self, payload: dict[str, Any]) -> LLMResponse:
        if "choices" not in payload or not payload["choices"]:
            raise LLMError("OpenAI response missing 'choices' field")

        choice = payload["choices"][0]
        finish_reason = FinishReason(str(choice.get("finish_reason", "stop")))
        message: dict[str, Any] = choice.get("message", {})

        content: str | None = message.get("content")
        tool_calls: list[ToolCall] = []

        raw_tool_calls: list[dict[str, Any]] = message.get("tool_calls") or []
        for tc in raw_tool_calls:
            func: dict[str, Any] = tc.get("function", {})
            try:
                arguments: dict[str, Any] = (
                    json.loads(func.get("arguments", "{}")) if func.get("arguments") else {}
                )
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=str(tc.get("id", "")),
                    name=str(func.get("name", "")),
                    arguments=arguments,
                )
            )

        usage = None
        if "usage" in payload:
            u: dict[str, Any] = payload["usage"]
            usage = UsageStats(
                prompt_tokens=int(u.get("prompt_tokens", 0)),
                completion_tokens=int(u.get("completion_tokens", 0)),
                total_tokens=int(u.get("total_tokens", 0)),
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=str(payload.get("model", self._config.model)),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((LLMRateLimitError, LLMTimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _make_request_with_retry(
        self, client: httpx.AsyncClient, url: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await client.post(url, json=payload)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"OpenAI request timed out: {e}") from e

        if response.status_code == 200:
            result: dict[str, Any] = response.json()
            return result

        error_msg = self._extract_api_error(response)

        if response.status_code == 401 or response.status_code == 403:
            raise LLMAuthenticationError(
                f"OpenAI auth error ({response.status_code}): {error_msg}"
            )
        if response.status_code == 429:
            raise LLMRateLimitError(
                f"OpenAI rate limit ({response.status_code}): {error_msg}"
            )
        if response.status_code >= 500:
            raise LLMTimeoutError(
                f"OpenAI server error ({response.status_code}): {error_msg}"
            )
        raise LLMError(
            f"OpenAI client error ({response.status_code}): {error_msg}"
        )

    async def _make_request_with_retry_configurable(
        self, client: httpx.AsyncClient, url: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        retry_decorator = retry(
            stop=stop_after_attempt(self._config.retry_max_attempts),
            wait=wait_exponential(
                multiplier=1,
                min=self._config.retry_min_wait,
                max=self._config.retry_max_wait,
            ),
            retry=retry_if_exception_type((LLMRateLimitError, LLMTimeoutError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

        @retry_decorator
        async def _do_request() -> dict[str, Any]:
            try:
                response = await client.post(url, json=payload)
            except httpx.TimeoutException as e:
                raise LLMTimeoutError(f"OpenAI request timed out: {e}") from e

            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                return result

            error_msg = self._extract_api_error(response)

            if response.status_code in (401, 403):
                raise LLMAuthenticationError(
                    f"OpenAI auth error ({response.status_code}): {error_msg}"
                )
            if response.status_code == 429:
                raise LLMRateLimitError(
                    f"OpenAI rate limit ({response.status_code}): {error_msg}"
                )
            if response.status_code >= 500:
                raise LLMTimeoutError(
                    f"OpenAI server error ({response.status_code}): {error_msg}"
                )
            raise LLMError(
                f"OpenAI client error ({response.status_code}): {error_msg}"
            )

        return await _do_request()

    @staticmethod
    def _extract_api_error_from_bytes(data: bytes) -> str:
        try:
            msg: object = json.loads(data).get("error", {}).get("message", data.decode())
            return str(msg)
        except Exception:
            return data.decode(errors="replace")
