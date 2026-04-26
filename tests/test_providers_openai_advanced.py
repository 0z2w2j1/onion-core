"""OpenAI Provider 高级测试：边界场景、错误处理、多模态等。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onion_core.models import (
    AgentContext,
    ContentBlock,
    FinishReason,
    ImageUrl,
    Message,
    ProviderError,
)
from onion_core.providers.openai import OpenAIProvider


def make_context():
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


def _mock_choice(content: str, finish_reason: str = "stop", tool_calls: list | None = None):
    return SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=tool_calls),
        finish_reason=finish_reason,
    )


def _mock_openai_resp(content: str = "", finish_reason: str = "stop", tool_calls: list | None = None, with_usage: bool = True):
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15) if with_usage else None
    return SimpleNamespace(
        choices=[_mock_choice(content, finish_reason, tool_calls)],
        usage=usage,
        model="gpt-4o",
    )


def _delta_ns(**kw):
    return SimpleNamespace(tool_calls=None, **kw)


class TestOpenAIProviderEdgeCases:
    """测试 OpenAI Provider 边界场景。"""

    @pytest.mark.asyncio
    async def test_complete_with_empty_response(self):
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_openai_resp(content="", with_usage=False)
            )
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())
            assert response.content == ""
            assert response.finish_reason == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_complete_with_none_usage(self):
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_openai_resp(content="Test", with_usage=False)
            )
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())
            assert response.usage is None

    @pytest.mark.asyncio
    async def test_complete_with_multimodal_content(self):
        context = AgentContext(
            messages=[
                Message(
                    role="user",
                    content=[
                        ContentBlock(type="text", text="What's in this image?"),
                        ContentBlock(type="image_url", image_url=ImageUrl(url="https://example.com/image.jpg")),
                    ],
                ),
            ]
        )
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            resp = SimpleNamespace(choices=[_mock_choice("It's a cat")], usage=None, model="gpt-4-vision")
            mock_client.chat.completions.create = AsyncMock(return_value=resp)
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(context)
            assert response.content == "It's a cat"
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert "messages" in call_kwargs

    @pytest.mark.asyncio
    async def test_complete_with_temperature_and_max_tokens(self):
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_openai_resp(content="Test", with_usage=False)
            )
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key", temperature=0.5, max_tokens=500)
            await provider.complete(make_context())
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["temperature"] == 0.5
            assert call_kwargs["max_tokens"] == 500

    @pytest.mark.asyncio
    async def test_stream_with_tool_call_delta(self):
        async def mock_stream():
            tc = SimpleNamespace(index=0, id="call_123", function=SimpleNamespace(name="get_weather", arguments="{}"))
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[tc]), finish_reason=None)])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None), finish_reason="tool_calls")])

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            chunks = []
            async for chunk in provider.stream(make_context()):
                chunks.append(chunk)
            assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_stream_iteration_error_handling(self):
        async def mock_stream_with_error():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=_delta_ns(content="Start"), finish_reason=None)])
            raise Exception("Stream interrupted")

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream_with_error())
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            with pytest.raises(ProviderError, match="OpenAI streaming error"):
                async for _ in provider.stream(make_context()):
                    pass

    @pytest.mark.asyncio
    async def test_build_messages_with_complex_content(self):
        context = AgentContext(
            messages=[
                Message(role="system", content="System instruction"),
                Message(role="user", content=[ContentBlock(type="text", text="First part"), ContentBlock(type="text", text="Second part")]),
                Message(role="assistant", content="Response"),
            ]
        )
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(api_key="test-key")
            messages = provider._build_messages(context)
            assert len(messages) == 3
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert messages[2]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_provider_with_custom_headers(self):
        with patch("openai.AsyncOpenAI") as mock_client_class:
            OpenAIProvider(api_key="test-key", default_headers={"X-Custom-Header": "custom-value"})
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["default_headers"]["X-Custom-Header"] == "custom-value"

    @pytest.mark.asyncio
    async def test_complete_with_content_filter_finish_reason(self):
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_openai_resp(content=None, finish_reason="content_filter", with_usage=False)
            )
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())
            assert response.finish_reason == FinishReason.CONTENT_FILTER

    @pytest.mark.asyncio
    async def test_complete_with_length_finish_reason(self):
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_openai_resp(content="Truncated response", finish_reason="length", with_usage=False)
            )
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())
            assert response.finish_reason == FinishReason.LENGTH

    @pytest.mark.asyncio
    async def test_stream_with_no_content_chunks(self):
        async def mock_stream():
            yield SimpleNamespace(choices=[])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=_delta_ns(content=""), finish_reason=None)])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=_delta_ns(content="Actual content"), finish_reason="stop")])

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
            mock_client_class.return_value = mock_client
            provider = OpenAIProvider(api_key="test-key")
            chunks = []
            async for chunk in provider.stream(make_context()):
                chunks.append(chunk)
            assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_complete_with_organization_parameter(self):
        with patch("openai.AsyncOpenAI") as mock_client_class:
            OpenAIProvider(api_key="test-key", organization="org-test123")
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["organization"] == "org-test123"

    @pytest.mark.asyncio
    async def test_name_property(self):
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(api_key="test-key", model="gpt-4-turbo")
            assert provider.name == "OpenAIProvider(gpt-4-turbo)"
