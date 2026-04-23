"""Anthropic Provider 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onion_core.models import AgentContext, FinishReason, Message, ProviderError
from onion_core.providers.anthropic import AnthropicProvider


@pytest.fixture
def mock_anthropic_response():
    """模拟 Anthropic API 响应。"""
    response = MagicMock()
    response.content = [
        MagicMock(
            type="text",
            text="Hello from Claude!",
        )
    ]
    response.stop_reason = "end_turn"
    response.usage = MagicMock(
        input_tokens=10,
        output_tokens=5,
    )
    response.model = "claude-3-5-sonnet-20241022"
    return response


@pytest.fixture
def mock_anthropic_tool_response():
    """模拟 Anthropic 工具调用响应。"""
    response = MagicMock()
    response.content = [
        MagicMock(
            type="tool_use",
            id="toolu_123",
            name="get_weather",
            input={"city": "Beijing"},
        )
    ]
    response.stop_reason = "tool_use"
    response.usage = None
    response.model = "claude-3-5-sonnet-20241022"
    return response


@pytest.fixture
def context():
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


class TestAnthropicProviderInit:
    """测试 AnthropicProvider 初始化。"""

    def test_init_basic(self):
        """基本初始化。"""
        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            assert provider.name == "AnthropicProvider(claude-3-5-sonnet-20241022)"

    def test_init_with_custom_params(self):
        """带自定义参数初始化。"""
        with patch("anthropic.AsyncAnthropic") as mock_client:
            AnthropicProvider(
                api_key="test-key",
                model="claude-3-opus-20240229",
                max_tokens=2048,
                temperature=0.7,
                base_url="https://custom.api.com",
            )
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["api_key"] == "test-key"
            assert call_kwargs["base_url"] == "https://custom.api.com"

    def test_init_missing_anthropic_package(self):
        """缺少 anthropic 包时抛出 ImportError。"""
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            pytest.raises(ImportError, match="anthropic package is required"),
        ):
            AnthropicProvider(api_key="test-key")


class TestAnthropicProviderSplitMessages:
    """测试 _split_messages 辅助方法。"""

    def test_split_system_message(self, context):
        """分离 system 消息。"""
        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            system, messages = provider._split_messages(context)
            
            assert system == "You are a helpful assistant."
            assert len(messages) == 1
            assert messages[0]["role"] == "user"

    def test_split_multiple_system_messages(self):
        """多个 system 消息合并。"""
        context = AgentContext(
            messages=[
                Message(role="system", content="System 1"),
                Message(role="system", content="System 2"),
                Message(role="user", content="Hello"),
            ]
        )
        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            system, messages = provider._split_messages(context)
            
            assert "System 1" in system
            assert "System 2" in system
            assert len(messages) == 1

    def test_split_tool_result_message(self):
        """处理 tool 结果消息。"""
        context = AgentContext(
            messages=[
                Message(role="user", content="What's the weather?"),
                Message(role="assistant", content="Let me check"),
                Message(role="tool", content="Sunny", name="toolu_123"),
            ]
        )
        with patch("anthropic.AsyncAnthropic"):
            provider = AnthropicProvider(api_key="test-key")
            system, messages = provider._split_messages(context)
            
            assert len(messages) == 3
            # 最后一个应该是 tool_result
            tool_msg = messages[-1]
            assert tool_msg["role"] == "user"
            assert tool_msg["content"][0]["type"] == "tool_result"
            assert tool_msg["content"][0]["tool_use_id"] == "toolu_123"


class TestAnthropicProviderComplete:
    """测试 AnthropicProvider.complete() 方法。"""

    @pytest.mark.asyncio
    async def test_complete_basic(self, context, mock_anthropic_response):
        """基本非流式调用。"""
        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_anthropic_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(context)

            assert response.content == "Hello from Claude!"
            assert response.finish_reason == FinishReason.STOP
            assert response.model == "claude-3-5-sonnet-20241022"
            assert response.usage is not None
            assert response.usage.prompt_tokens == 10
            assert response.usage.completion_tokens == 5
            assert len(response.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_complete_with_text_blocks(self, context):
        """多个 text block 拼接。"""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(type="text", text="Hello "),
            MagicMock(type="text", text="from "),
            MagicMock(type="text", text="Claude!"),
        ]
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_response.model = "claude-3-5-sonnet-20241022"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(context)

            assert response.content == "Hello from Claude!"

    @pytest.mark.asyncio
    async def test_complete_with_tool_calls(self, context, mock_anthropic_tool_response):
        """带工具调用的响应。"""
        # 修复 Mock 对象的 name 属性
        mock_tool_use = mock_anthropic_tool_response.content[0]
        mock_tool_use.name = "get_weather"
        
        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_anthropic_tool_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            response = await provider.complete(context)

            assert response.content is None
            assert response.finish_reason == FinishReason.TOOL_CALLS
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0].name == "get_weather"
            assert response.tool_calls[0].arguments == {"city": "Beijing"}

    @pytest.mark.asyncio
    async def test_complete_api_error(self, context):
        """API 调用失败时抛出 ProviderError。"""
        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API Error"))
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            with pytest.raises(ProviderError, match="Anthropic API error"):
                await provider.complete(context)

    @pytest.mark.asyncio
    async def test_complete_with_tools_config(self, context):
        """从 context.config 读取工具定义。"""
        context.config["tools"] = [
            {
                "name": "get_weather",
                "description": "Get weather for a city",
            }
        ]

        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Test")]
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_response.model = "claude-3-5-sonnet-20241022"

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            await provider.complete(context)

            # 验证 tools 参数被传递
            call_kwargs = mock_client.messages.create.call_args[1]
            assert "tools" in call_kwargs


class TestAnthropicProviderStream:
    """测试 AnthropicProvider.stream() 方法。"""

    @pytest.mark.asyncio
    async def test_stream_basic(self, context):
        """基本流式调用。"""
        # 模拟 stream 上下文管理器
        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)
        
        # 模拟文本流
        async def text_stream():
            yield "Hello"
            yield " from"
            yield " Claude!"
        
        mock_stream.text_stream = text_stream()
        
        # 模拟最终消息
        final_message = MagicMock()
        final_message.stop_reason = "end_turn"
        mock_stream.get_final_message = AsyncMock(return_value=final_message)

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.stream = MagicMock(return_value=mock_stream)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            chunks = []
            async for chunk in provider.stream(context):
                chunks.append(chunk)

            assert len(chunks) >= 3  # 至少 3 个文本块 + 1 个结束块
            assert chunks[0].delta == "Hello"
            assert chunks[-1].finish_reason == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_stream_api_error(self, context):
        """流式 API 调用失败时抛出 ProviderError。"""
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(side_effect=Exception("Stream Error"))
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("anthropic.AsyncAnthropic") as mock_client_class:
            mock_client = MagicMock()
            mock_client.messages.stream = MagicMock(return_value=mock_stream_ctx)
            mock_client_class.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            with pytest.raises(ProviderError, match="Anthropic streaming error"):
                async for _ in provider.stream(context):
                    pass

    @pytest.mark.asyncio
    async def test_stream_finish_reason_mapping(self, context):
        """测试 stop_reason 到 FinishReason 的映射。"""
        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)
        
        async def text_stream():
            yield "Test"
        
        mock_stream.text_stream = text_stream()
        
        # 测试不同的 stop_reason
        test_cases = [
            ("end_turn", FinishReason.STOP),
            ("max_tokens", FinishReason.LENGTH),
            ("tool_use", FinishReason.TOOL_CALLS),
            ("refusal", FinishReason.CONTENT_FILTER),
        ]

        for stop_reason, expected_finish in test_cases:
            final_message = MagicMock()
            final_message.stop_reason = stop_reason
            mock_stream.get_final_message = AsyncMock(return_value=final_message)

            with patch("anthropic.AsyncAnthropic") as mock_client_class:
                mock_client = MagicMock()
                mock_client.messages.stream = MagicMock(return_value=mock_stream)
                mock_client_class.return_value = mock_client

                provider = AnthropicProvider(api_key="test-key")
                chunks = []
                async for chunk in provider.stream(context):
                    chunks.append(chunk)
                
                assert chunks[-1].finish_reason == expected_finish
