"""
Onion Core - 国内 AI Provider 适配器 (DeepSeek, ZhipuAI, DashScope, Moonshot)

所有这些 Provider 都基于 OpenAI 兼容协议，因此它们都继承自 OpenAIProvider，
只需预设对应的 base_url 即可。

依赖：pip install openai>=1.0
"""

from __future__ import annotations

from .openai import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """
    DeepSeek API 适配器 (V3 / R1)。
    官网：https://www.deepseek.com/
    """
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.deepseek.com",
            max_tokens=max_tokens,
            temperature=temperature,
        )


class ZhipuAIProvider(OpenAIProvider):
    """
    智谱 AI (GLM) API 适配器。
    官网：https://open.bigmodel.cn/
    """
    def __init__(
        self,
        api_key: str,
        model: str = "glm-4",
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            max_tokens=max_tokens,
            temperature=temperature,
        )


class MoonshotProvider(OpenAIProvider):
    """
    Moonshot (Kimi) API 适配器。
    官网：https://www.moonshot.cn/
    """
    def __init__(
        self,
        api_key: str,
        model: str = "moonshot-v1-8k",
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.moonshot.cn/v1",
            max_tokens=max_tokens,
            temperature=temperature,
        )


class DashScopeProvider(OpenAIProvider):
    """
    阿里通义千问 (DashScope) OpenAI 兼容 API 适配器。
    官网：https://dashscope.aliyuncs.com/
    """
    def __init__(
        self,
        api_key: str,
        model: str = "qwen-turbo",
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            max_tokens=max_tokens,
            temperature=temperature,
        )
