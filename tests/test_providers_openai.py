"""OpenAI Provider 单元测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onion_core.models import AgentContext, Message, ProviderError
from onion_core.providers.openai import OpenAIProvider


@pytest.fixture
def mock_openai_response():
    """模拟 OpenAI API 响应。"""
    response = MagicMock()
    response.choices = [
        MagicMock(
            message=MagicMock(
                content="Hello from OpenAI!",
                tool_calls=None,
            ),
            finish_reason="stop",
        )
    ]
    response.usage = MagicMock(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    response.model = "gpt-4o"
    return response


@pytest.fixture
def mock_openai_stream_response():
    """模拟 OpenAI 流式响应。"""
    chunks = [
        MagicMock(
            choices=[
                MagicMock(
                    delta=MagicMock(content="Hello"),
                    finish_reason=None,
                )
            ]
        ),
        MagicMock(
            choices=[
                MagicMock(
                    delta=MagicMock(content=" from"),
                    finish_reason=None,
                )
            ]
        ),
        MagicMock(
            choices=[
                MagicMock(
                    delta=MagicMock(content=" OpenAI!"),
                    finish_reason="stop",
                )
            ]
        ),
    ]
    
    async def async_gen():
        for chunk in chunks:
            yield chunk
    
    return async_gen()


@pytest.fixture
def context():
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


class TestOpenAIProviderInit:
    """测试 OpenAIProvider 初始化。"""

    def test_init_basic(self):
        """基本初始化。"""
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
            assert provider.name == "OpenAIProvider(gpt-4o)"

    def test_init_with_custom_params(self):
        """带自定义参数初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            OpenAIProvider(
                api_key="test-key",
                model="gpt-3.5-turbo",
                base_url="https://custom.api.com",
                organization="org-123",
                max_tokens=1000,
                temperature=0.7,
            )
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["api_key"] == "test-key"
            assert call_kwargs["base_url"] == "https://custom.api.com"
            assert call_kwargs["organization"] == "org-123"

    def test_init_missing_openai_package(self):
        """缺少 openai 包时抛出 ImportError。"""
        with (
            patch.dict("sys.modules", {"openai": None}),
            pytest.raises(ImportError, match="openai package is required"),
        ):
            OpenAIProvider(api_key="test-key")


class TestOpenAIProviderComplete:
    """测试 OpenAIProvider.complete() 方法。"""

    @pytest.mark.asyncio
    async def test_complete_basic(self, context, mock_openai_response):
        """基本非流式调用。"""
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_openai_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
            response = await provider.complete(context)

            assert response.content == "Hello from OpenAI!"
            assert response.finish_reason == "stop"
            assert response.model == "gpt-4o"
            assert response.usage is not None
            assert response.usage.prompt_tokens == 10
            assert response.usage.completion_tokens == 5
            assert response.usage.total_tokens == 15
            assert len(response.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_complete_with_tool_calls(self, context):
        """带工具调用的响应。"""
        # 创建 mock tool call 对象
        mock_function = MagicMock()
        mock_function.name = "get_weather"
        mock_function.arguments = json.dumps({"city": "Beijing"})
        
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function = mock_function
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=None,
                    tool_calls=[mock_tool_call],
                ),
                finish_reason="tool_calls",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(context)

            assert response.content is None
            assert response.finish_reason == "tool_calls"
            assert len(response.tool_calls) == 1
            tool_call = response.tool_calls[0]
            assert tool_call.name == "get_weather"
            assert tool_call.arguments == {"city": "Beijing"}

    @pytest.mark.asyncio
    async def test_complete_with_invalid_json(self, context):
        """工具调用参数为无效 JSON 时的处理。"""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=None,
                    tool_calls=[
                        MagicMock(
                            id="call_123",
                            function=MagicMock(
                                **{"name": "test_tool"},
                                arguments="{invalid json}",
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            response = await provider.complete(context)

            assert len(response.tool_calls) == 1
            assert "_raw" in response.tool_calls[0].arguments

    @pytest.mark.asyncio
    async def test_complete_api_error(self, context):
        """API 调用失败时抛出 ProviderError。"""
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("API Error")
            )
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            with pytest.raises(ProviderError, match="OpenAI API error"):
                await provider.complete(context)

    @pytest.mark.asyncio
    async def test_complete_with_tools_config(self, context):
        """从 context.config 读取工具定义。"""
        context.config["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                },
            }
        ]

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
            await provider.complete(context)

            # 验证 tools 参数被传递
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert "tools" in call_kwargs


class TestOpenAIProviderStream:
    """测试 OpenAIProvider.stream() 方法。"""

    @pytest.mark.asyncio
    async def test_stream_basic(self, context, mock_openai_stream_response):
        """基本流式调用。"""
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_openai_stream_response
            )
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            chunks = []
            async for chunk in provider.stream(context):
                chunks.append(chunk)

            assert len(chunks) == 3
            assert chunks[0].delta == "Hello"
            assert chunks[1].delta == " from"
            assert chunks[2].delta == " OpenAI!"
            assert chunks[2].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_stream_api_error(self, context):
        """流式 API 调用失败时抛出 ProviderError。"""
        with patch("openai.AsyncOpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("Stream Error")
            )
            mock_client_class.return_value = mock_client

            provider = OpenAIProvider(api_key="test-key")
            with pytest.raises(ProviderError, match="OpenAI API error"):
                async for _ in provider.stream(context):
                    pass

    @pytest.mark.asyncio
    async def test_stream_empty_choices(self, context):
        """处理空 choices 的情况。"""
        async def mock_stream():
            yield MagicMock(choices=[])
            yield MagicMock(
                choices=[
                    MagicMock(
                        delta=MagicMock(content="Test"),
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
            async for chunk in provider.stream(context):
                chunks.append(chunk)

            assert len(chunks) == 1
            assert chunks[0].delta == "Test"


class TestOpenAIProviderBuildMessages:
    """测试 _build_messages 辅助方法。"""

    def test_build_messages_simple(self, context):
        """简单消息构建。"""
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(api_key="test-key")
            messages = provider._build_messages(context)

            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"

    def test_build_messages_with_none_fields(self):
        """过滤 None 字段。"""
        context = AgentContext(
            messages=[
                Message(role="user", content="Test", name=None),
            ]
        )
        with patch("openai.AsyncOpenAI"):
            provider = OpenAIProvider(api_key="test-key")
            messages = provider._build_messages(context)

            assert len(messages) == 1
            assert "name" not in messages[0] or messages[0]["name"] is None
