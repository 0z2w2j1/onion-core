"""Anthropic Provider 高级测试：完整覆盖所有代码路径。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onion_core.models import (
    AgentContext,
    ContentBlock,
    FinishReason,
    Message,
    ProviderError,
)
from onion_core.providers.anthropic import AnthropicProvider


def make_context():
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


class TestAnthropicProviderAdvanced:
    """Anthropic Provider 高级功能测试。"""

    @pytest.mark.asyncio
    async def test_complete_with_multiple_text_blocks(self):
        """处理多个文本块响应。"""
        mock_block1 = MagicMock(type="text", text="First part ")
        mock_block2 = MagicMock(type="text", text="Second part")
        
        mock_response = MagicMock()
        mock_response.content = [mock_block1, mock_block2]
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=20)
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.content == "First part Second part"
            assert response.usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_complete_with_tool_use_blocks(self):
        """处理工具调用块。"""
        mock_tool_block = MagicMock(
            type="tool_use",
            id="toolu_123",
            name="get_weather",
            input={"city": "Beijing"},
        )
        # 确保name是字符串
        type(mock_tool_block).name = property(lambda self: "get_weather")
        
        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.stop_reason = "tool_use"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.content is None
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0].name == "get_weather"
            assert response.tool_calls[0].arguments == {"city": "Beijing"}
            assert response.finish_reason == FinishReason.TOOL_CALLS

    @pytest.mark.asyncio
    async def test_complete_with_mixed_text_and_tool_blocks(self):
        """处理混合文本和工具调用块。"""
        mock_text_block = MagicMock(type="text", text="Let me check the weather.")
        mock_tool_block = MagicMock(
            type="tool_use",
            id="toolu_123",
            name="get_weather",
            input={"city": "Beijing"},
        )
        # 确保name是字符串
        type(mock_tool_block).name = property(lambda self: "get_weather")
        
        mock_response = MagicMock()
        mock_response.content = [mock_text_block, mock_tool_block]
        mock_response.stop_reason = "tool_use"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.content == "Let me check the weather."
            assert len(response.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_split_messages_with_system_role(self):
        """分离系统消息。"""
        context = AgentContext(
            messages=[
                Message(role="system", content="System instruction 1"),
                Message(role="user", content="User message"),
                Message(role="system", content="System instruction 2"),
            ]
        )

        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            system, messages = provider._split_messages(context)

            assert "System instruction 1" in system
            assert "System instruction 2" in system
            assert len(messages) == 1
            assert messages[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_split_messages_with_tool_result(self):
        """处理工具结果消息。"""
        context = AgentContext(
            messages=[
                Message(role="user", content="What's the weather?"),
                Message(
                    role="assistant",
                    content="",
                    name=None,
                ),
                Message(
                    role="tool",
                    content="Sunny, 25°C",
                    name="toolu_123",
                ),
            ]
        )

        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            system, messages = provider._split_messages(context)

            assert system == ""
            # assistant空消息也会被保留
            assert len(messages) == 3
            # 验证tool结果被正确转换
            tool_msg = messages[2]
            assert tool_msg["role"] == "user"
            assert tool_msg["content"][0]["type"] == "tool_result"
            assert tool_msg["content"][0]["tool_use_id"] == "toolu_123"

    @pytest.mark.asyncio
    async def test_split_messages_with_multimodal_content(self):
        """处理多模态内容块。"""
        context = AgentContext(
            messages=[
                Message(
                    role="user",
                    content=[
                        ContentBlock(type="text", text="What's in this image?"),
                        ContentBlock(
                            type="image",
                            source={"type": "base64", "media_type": "image/jpeg", "data": "base64data"},
                        ),
                    ],
                ),
            ]
        )

        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            system, messages = provider._split_messages(context)

            assert len(messages) == 1
            content = messages[0]["content"]
            assert isinstance(content, list)
            assert len(content) == 2
            assert content[0]["type"] == "text"
            assert content[1]["type"] == "image"

    @pytest.mark.asyncio
    async def test_complete_with_custom_max_tokens(self):
        """自定义max_tokens参数。"""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Response")]
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key", max_tokens=2048)
            await provider.complete(make_context())

            call_kwargs = mock_client.messages.create.call_args[1]
            assert call_kwargs["max_tokens"] == 2048

    @pytest.mark.asyncio
    async def test_complete_with_temperature(self):
        """自定义temperature参数。"""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Response")]
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key", temperature=0.7)
            await provider.complete(make_context())

            call_kwargs = mock_client.messages.create.call_args[1]
            assert call_kwargs["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_complete_with_tools_config(self):
        """从context.config读取工具定义。"""
        context = make_context()
        context.config["tools"] = [
            {
                "name": "get_weather",
                "description": "Get weather for a city",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            }
        ]

        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Response")]
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            await provider.complete(context)

            call_kwargs = mock_client.messages.create.call_args[1]
            assert "tools" in call_kwargs

    @pytest.mark.asyncio
    async def test_complete_api_error_handling(self):
        """API错误处理。"""
        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                side_effect=Exception("API Error")
            )
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            
            with pytest.raises(ProviderError, match="Anthropic API error"):
                await provider.complete(make_context())

    @pytest.mark.asyncio
    async def test_stream_basic_flow(self):
        """基本流式调用流程。"""
        # 创建正确的异步迭代器
        async def mock_text_stream():
            yield "Hello"
            yield " World"
        
        mock_stream = MagicMock()
        mock_stream.text_stream = mock_text_stream()
        
        async def mock_get_final():
            return MagicMock(stop_reason="end_turn")
        
        mock_stream.get_final_message = mock_get_final
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.stream = MagicMock(return_value=mock_stream)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            chunks = []
            async for chunk in provider.stream(make_context()):
                chunks.append(chunk)

            assert len(chunks) >= 2
            assert chunks[0].delta == "Hello"
            assert chunks[1].delta == " World"
            assert chunks[-1].finish_reason == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_stream_api_error(self):
        """流式API错误处理。"""
        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.stream = MagicMock(
                side_effect=Exception("Stream Error")
            )
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            
            with pytest.raises(ProviderError, match="Anthropic streaming error"):
                async for _ in provider.stream(make_context()):
                    pass

    @pytest.mark.asyncio
    async def test_stream_finish_reason_mapping(self):
        """流式响应结束原因映射。"""
        async def mock_text_stream():
            yield "Response"
        
        mock_stream = MagicMock()
        mock_stream.text_stream = mock_text_stream()
        
        async def mock_get_final():
            return MagicMock(stop_reason="max_tokens")
        
        mock_stream.get_final_message = mock_get_final
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.stream = MagicMock(return_value=mock_stream)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            chunks = []
            async for chunk in provider.stream(make_context()):
                chunks.append(chunk)

            assert chunks[-1].finish_reason == FinishReason.LENGTH

    @pytest.mark.asyncio
    async def test_init_with_base_url(self):
        """自定义base_url初始化。"""
        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            AnthropicProvider(
                api_key="test-key",
                base_url="https://custom.anthropic.com",
            )
            
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["base_url"] == "https://custom.anthropic.com"

    @pytest.mark.asyncio
    async def test_init_missing_anthropic_package(self):
        """缺少anthropic包时抛出ImportError。"""
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            pytest.raises(ImportError, match="anthropic package is required"),
        ):
            AnthropicProvider(api_key="test-key")

    @pytest.mark.asyncio
    async def test_name_property(self):
        """Provider名称属性。"""
        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key", model="claude-3-opus")
            assert provider.name == "AnthropicProvider(claude-3-opus)"

    @pytest.mark.asyncio
    async def test_complete_with_refusal_stop_reason(self):
        """处理拒绝响应的结束原因。"""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="I cannot help with that.")]
        mock_response.stop_reason = "refusal"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.finish_reason == FinishReason.CONTENT_FILTER

    @pytest.mark.asyncio
    async def test_complete_with_pause_turn_stop_reason(self):
        """处理pause_turn结束原因。"""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Paused")]
        mock_response.stop_reason = "pause_turn"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.finish_reason == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_split_messages_empty_system(self):
        """无系统消息时的处理。"""
        context = AgentContext(
            messages=[
                Message(role="user", content="Hello"),
                Message(role="assistant", content="Hi there"),
            ]
        )

        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            system, messages = provider._split_messages(context)

            assert system == ""
            assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_complete_with_no_content_blocks(self):
        """处理无内容块的响应（边界情况）。"""
        mock_response = MagicMock()
        mock_response.content = []
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_response.model = "claude-3-sonnet"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(make_context())

            assert response.content is None
            assert len(response.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_build_tools_returns_none_when_not_configured(self):
        """未配置工具时返回None。"""
        context = make_context()
        context.config.pop("tools", None)

        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            tools = provider._build_tools(context)

            assert tools is None
