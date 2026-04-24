"""Test providers package exports."""

from __future__ import annotations


def test_providers_exports():
    """Test that all expected providers are exported."""
    from onion_core.providers import (
        AnthropicProvider,
        DashScopeProvider,
        DeepSeekProvider,
        LMStudioProvider,
        LocalProvider,
        MoonshotProvider,
        OllamaProvider,
        OpenAIProvider,
        ZhipuAIProvider,
    )
    
    # Verify all are classes
    assert isinstance(OpenAIProvider, type)
    assert isinstance(AnthropicProvider, type)
    assert isinstance(DeepSeekProvider, type)
    assert isinstance(ZhipuAIProvider, type)
    assert isinstance(MoonshotProvider, type)
    assert isinstance(DashScopeProvider, type)
    assert isinstance(LocalProvider, type)
    assert isinstance(OllamaProvider, type)
    assert isinstance(LMStudioProvider, type)


def test_providers_all_list():
    """Test __all__ list contains all expected exports."""
    from onion_core import providers
    
    expected = [
        "OpenAIProvider",
        "AnthropicProvider",
        "DeepSeekProvider",
        "ZhipuAIProvider",
        "MoonshotProvider",
        "DashScopeProvider",
        "LocalProvider",
        "OllamaProvider",
        "LMStudioProvider",
    ]
    
    for name in expected:
        assert name in providers.__all__, f"{name} not in __all__"
        assert hasattr(providers, name), f"{name} not accessible"
