"""Local AI Providers 单元测试 (Ollama, LM Studio, LocalProvider)。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from onion_core.providers.local import LMStudioProvider, LocalProvider, OllamaProvider


class TestLocalProvider:
    """测试通用 Local Provider。"""

    def test_init_basic(self):
        """基本初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            LocalProvider(
                base_url="http://localhost:8000/v1",
                model="llama-3",
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "http://localhost:8000/v1"
            assert call_kwargs["api_key"] == "not-needed"

    def test_init_with_custom_api_key(self):
        """自定义 API Key。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            LocalProvider(
                base_url="http://localhost:8000/v1",
                api_key="my-secret-key",
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["api_key"] == "my-secret-key"

    def test_name_property(self):
        """测试 name 属性。"""
        with patch("openai.AsyncOpenAI"):
            provider = LocalProvider(base_url="http://test.com", model="test-model")
            assert "test-model" in provider.name


class TestOllamaProvider:
    """测试 Ollama Provider。"""

    def test_init_default(self):
        """默认初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            provider = OllamaProvider(model="llama3")
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "http://localhost:11434/v1"
            assert call_kwargs["api_key"] == "ollama"
            assert "llama3" in provider.name.lower()

    def test_init_custom_base_url(self):
        """自定义 base_url。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            OllamaProvider(
                model="mistral",
                base_url="http://192.168.1.100:11434/v1",
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "http://192.168.1.100:11434/v1"

    def test_init_with_params(self):
        """带参数初始化。"""
        with patch("openai.AsyncOpenAI"):
            provider = OllamaProvider(
                model="qwen2.5",
                max_tokens=2048,
                temperature=0.7,
            )
            assert provider._max_tokens == 2048
            assert provider._temperature == 0.7


class TestLMStudioProvider:
    """测试 LM Studio Provider。"""

    def test_init_default(self):
        """默认初始化。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            LMStudioProvider()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "http://localhost:1234/v1"
            assert call_kwargs["api_key"] == "lm-studio"

    def test_init_custom_model(self):
        """自定义模型。"""
        with patch("openai.AsyncOpenAI"):
            provider = LMStudioProvider(model="llama-3-8b")
            assert "llama-3-8b" in provider.name.lower()

    def test_init_custom_base_url(self):
        """自定义 base_url。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            LMStudioProvider(
                base_url="http://192.168.1.50:1234/v1",
            )
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "http://192.168.1.50:1234/v1"

    def test_init_with_params(self):
        """带参数初始化。"""
        with patch("openai.AsyncOpenAI"):
            provider = LMStudioProvider(
                model="gemma-2",
                max_tokens=1024,
                temperature=0.5,
            )
            assert provider._max_tokens == 1024
            assert provider._temperature == 0.5


class TestLocalProvidersInheritance:
    """测试本地 Provider 继承关系。"""

    def test_local_is_openai_provider(self):
        """LocalProvider 继承自 OpenAIProvider。"""
        from onion_core.providers.openai import OpenAIProvider
        
        with patch("openai.AsyncOpenAI"):
            provider = LocalProvider(base_url="http://test.com")
            assert isinstance(provider, OpenAIProvider)

    def test_ollama_is_openai_provider(self):
        """OllamaProvider 继承自 OpenAIProvider。"""
        from onion_core.providers.openai import OpenAIProvider
        
        with patch("openai.AsyncOpenAI"):
            provider = OllamaProvider(model="test")
            assert isinstance(provider, OpenAIProvider)

    def test_lmstudio_is_openai_provider(self):
        """LMStudioProvider 继承自 OpenAIProvider。"""
        from onion_core.providers.openai import OpenAIProvider
        
        with patch("openai.AsyncOpenAI"):
            provider = LMStudioProvider()
            assert isinstance(provider, OpenAIProvider)


class TestLocalProviderEdgeCases:
    """测试边界情况。"""

    def test_ollama_requires_model(self):
        """Ollama 需要提供 model 参数。"""
        with (
            patch("openai.AsyncOpenAI"),
            pytest.raises(TypeError),
        ):
            OllamaProvider()  # type: ignore

    def test_local_requires_base_url(self):
        """LocalProvider 需要提供 base_url。"""
        with (
            patch("openai.AsyncOpenAI"),
            pytest.raises(TypeError),
        ):
            LocalProvider()  # type: ignore

    def test_lmstudio_default_values(self):
        """LMStudio 的默认值。"""
        with patch("openai.AsyncOpenAI") as mock_client:
            provider = LMStudioProvider()
            assert provider._model == "default"
            # 验证 base_url 被正确传递
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["base_url"] == "http://localhost:1234/v1"
