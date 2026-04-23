"""Onion Core providers package."""

from ..provider import EchoProvider, LLMProvider

__all__ = ["LLMProvider", "EchoProvider"]

# 懒加载，避免在未安装 SDK 时报错
def __getattr__(name: str):
    if name == "OpenAIProvider":
        from .openai import OpenAIProvider
        return OpenAIProvider
    if name == "AnthropicProvider":
        from .anthropic import AnthropicProvider
        return AnthropicProvider
    if name in ("DeepSeekProvider", "ZhipuAIProvider", "MoonshotProvider", "DashScopeProvider"):
        from .domestic import DashScopeProvider, DeepSeekProvider, MoonshotProvider, ZhipuAIProvider
        if name == "DeepSeekProvider":
            return DeepSeekProvider
        if name == "ZhipuAIProvider":
            return ZhipuAIProvider
        if name == "MoonshotProvider":
            return MoonshotProvider
        if name == "DashScopeProvider":
            return DashScopeProvider
    if name in ("LocalProvider", "OllamaProvider", "LMStudioProvider"):
        from .local import LMStudioProvider, LocalProvider, OllamaProvider
        if name == "LocalProvider":
            return LocalProvider
        if name == "OllamaProvider":
            return OllamaProvider
        if name == "LMStudioProvider":
            return LMStudioProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
