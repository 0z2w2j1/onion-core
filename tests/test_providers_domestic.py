"""Domestic AI Providers 单元测试 (DeepSeek, ZhipuAI, Moonshot, DashScope)。"""

from __future__ import annotations

from unittest.mock import patch

from onion_core.providers.domestic import (
    DashScopeProvider,
    DeepSeekProvider,
    MoonshotProvider,
    ZhipuAIProvider,
)


class TestDeepSeekProvider:
    """测试 DeepSeek Provider。"""

    def test_init_default(self):
        """默认初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            provider = DeepSeekProvider(api_key="sk-test")
            assert "deepseek" in provider.name.lower()
            # 验证 base_url 被正确传递
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://api.deepseek.com"

    def test_init_custom_model(self):
        """自定义模型。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            DeepSeekProvider(
                api_key="sk-test",
                model="deepseek-reasoner",
                max_tokens=1000,
                temperature=0.5,
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://api.deepseek.com"


class TestZhipuAIProvider:
    """测试智谱 AI Provider。"""

    def test_init_default(self):
        """默认初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            provider = ZhipuAIProvider(api_key="test-key")
            assert "glm" in provider.name.lower()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://open.bigmodel.cn/api/paas/v4/"

    def test_init_custom_model(self):
        """自定义模型。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            ZhipuAIProvider(
                api_key="test-key",
                model="glm-4-flash",
                max_tokens=2048,
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://open.bigmodel.cn/api/paas/v4/"


class TestMoonshotProvider:
    """测试 Moonshot (Kimi) Provider。"""

    def test_init_default(self):
        """默认初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            provider = MoonshotProvider(api_key="sk-test")
            assert "moonshot" in provider.name.lower()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://api.moonshot.cn/v1"

    def test_init_custom_model(self):
        """自定义模型。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            MoonshotProvider(
                api_key="sk-test",
                model="moonshot-v1-32k",
                temperature=0.3,
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://api.moonshot.cn/v1"


class TestDashScopeProvider:
    """测试阿里通义千问 Provider。"""

    def test_init_default(self):
        """默认初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            provider = DashScopeProvider(api_key="sk-test")
            assert "qwen" in provider.name.lower()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_init_custom_model(self):
        """自定义模型。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            DashScopeProvider(
                api_key="sk-test",
                model="qwen-max",
                max_tokens=1500,
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"


class TestDomesticProvidersInheritance:
    """测试国内 Provider 继承关系。"""

    def test_deepseek_is_openai_provider(self):
        """DeepSeek 继承自 OpenAIProvider。"""
        from onion_core.providers.openai import OpenAIProvider
        
        with patch("openai.AsyncOpenAI"):
            provider = DeepSeekProvider(api_key="test")
            assert isinstance(provider, OpenAIProvider)

    def test_zhipuai_is_openai_provider(self):
        """智谱 AI 继承自 OpenAIProvider。"""
        from onion_core.providers.openai import OpenAIProvider
        
        with patch("openai.AsyncOpenAI"):
            provider = ZhipuAIProvider(api_key="test")
            assert isinstance(provider, OpenAIProvider)

    def test_moonshot_is_openai_provider(self):
        """Moonshot 继承自 OpenAIProvider。"""
        from onion_core.providers.openai import OpenAIProvider
        
        with patch("openai.AsyncOpenAI"):
            provider = MoonshotProvider(api_key="test")
            assert isinstance(provider, OpenAIProvider)

    def test_dashscope_is_openai_provider(self):
        """DashScope 继承自 OpenAIProvider。"""
        from onion_core.providers.openai import OpenAIProvider
        
        with patch("openai.AsyncOpenAI"):
            provider = DashScopeProvider(api_key="test")
            assert isinstance(provider, OpenAIProvider)
