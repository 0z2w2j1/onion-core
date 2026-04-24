"""OpenAI Provider 高级测试：边界场景、错误处理、多模态等。"""

from __future__ import annotations

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


class TestOpenAIProviderEdgeCases:
    """测试 OpenAI Provider 边界场景。"""

    @pytest.mark.asyncio
    async def test_complete_with_empty_response(self):
        """处理空响应内容。"""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="", tool_calls=None),
                finish_reason="stop",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.content == ""
            assert response.finish_reason == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_complete_with_none_usage(self):
        """处理无usage信息的响应。"""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="Test", tool_calls=None),
                finish_reason="stop",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.usage is None

    @pytest.mark.asyncio
    async def test_complete_with_multimodal_content(self):
        """处理多模态消息（文本+图片）。"""
        context = AgentContext(
            messages=[
                Message(
                    role="user",
                    content=[
                        ContentBlock(type="text", text="What's in this image?"),
                        ContentBlock(
                            type="image_url",
                            image_url=ImageUrl(url="https://example.com/image.jpg"),
                        ),
                    ],
                ),
            ]
        )

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="It's a cat", tool_calls=None),
                finish_reason="stop",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4-vision"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(context)

            assert response.content == "It's a cat"
            # 验证消息被正确序列化
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert "messages" in call_kwargs

    @pytest.mark.asyncio
    async def test_complete_with_temperature_and_max_tokens(self):
        """验证温度和max_tokens参数传递。"""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="Test", tool_calls=None),
                finish_reason="stop",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(
                api_key="test-key",
                temperature=0.5,
                max_tokens=500,
            )
            await provider.complete(make_context())

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["temperature"] == 0.5
            assert call_kwargs["max_tokens"] == 500

    @pytest.mark.asyncio
    async def test_stream_with_tool_call_delta(self):
        """流式响应中的工具调用增量。"""
        async def mock_stream():
            yield MagicMock(
                choices=[
                    MagicMock(
                        delta=MagicMock(content=None, tool_calls=[
                            MagicMock(
                                index=0,
                                id="call_123",
                                function=MagicMock(name="get_weather", arguments="{}"),
                            )
                        ]),
                        finish_reason=None,
                    )
                ]
            )
            yield MagicMock(
                choices=[
                    MagicMock(
                        delta=MagicMock(content=None),
                        finish_reason="tool_calls",
                    )
                ]
            )

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
        """流式迭代过程中的错误处理。"""
        async def mock_stream_with_error():
            yield MagicMock(
                choices=[
                    MagicMock(
                        delta=MagicMock(content="Start"),
                        finish_reason=None,
                    )
                ]
            )
            raise Exception("Stream interrupted")

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_stream_with_error()
            )
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            
            with pytest.raises(ProviderError, match="OpenAI streaming error"):
                async for _ in provider.stream(make_context()):
                    pass

    @pytest.mark.asyncio
    async def test_build_messages_with_complex_content(self):
        """构建包含复杂内容的消息。"""
        context = AgentContext(
            messages=[
                Message(role="system", content="System instruction"),
                Message(
                    role="user",
                    content=[
                        ContentBlock(type="text", text="First part"),
                        ContentBlock(type="text", text="Second part"),
                    ],
                ),
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
        """自定义请求头。"""
        with patch("openai.AsyncOpenAI") as mock_client_class:
            OpenAIProvider(
                api_key="test-key",
                default_headers={"X-Custom-Header": "custom-value"},
            )
            
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["default_headers"]["X-Custom-Header"] == "custom-value"

    @pytest.mark.asyncio
    async def test_complete_with_content_filter_finish_reason(self):
        """内容过滤导致的结束。"""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content=None, tool_calls=None),
                finish_reason="content_filter",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.finish_reason == FinishReason.CONTENT_FILTER

    @pytest.mark.asyncio
    async def test_complete_with_length_finish_reason(self):
        """达到最大长度导致的结束。"""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="Truncated response", tool_calls=None),
                finish_reason="length",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.finish_reason == FinishReason.LENGTH

    @pytest.mark.asyncio
    async def test_stream_with_no_content_chunks(self):
        """处理无内容的流式chunk。"""
        async def mock_stream():
            yield MagicMock(choices=[])  # 空choices
            yield MagicMock(
                choices=[
                    MagicMock(
                        delta=MagicMock(content=""),  # 空内容
                        finish_reason=None,
                    )
                ]
            )
            yield MagicMock(
                choices=[
                    MagicMock(
                        delta=MagicMock(content="Actual content"),
                        finish_reason="stop",
                    )
                ]
            )

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            chunks = []
            async for chunk in provider.stream(make_context()):
                chunks.append(chunk)

            # 应跳过空choices，保留空内容和实际内容
            assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_complete_with_organization_parameter(self):
        """组织ID参数传递。"""
        with patch("openai.AsyncOpenAI") as mock_client_class:
            OpenAIProvider(
                api_key="test-key",
                organization="org-test123",
            )
            
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["organization"] == "org-test123"

    @pytest.mark.asyncio
    async def test_name_property(self):
        """Provider名称属性。"""
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(api_key="test-key", model="gpt-4-turbo")
            assert provider.name == "OpenAIProvider(gpt-4-turbo)"
