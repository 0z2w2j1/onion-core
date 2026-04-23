# -*- coding: utf-8 -*-
"""
Onion Core - 本地/自建 AI Provider 适配器 (Ollama, vLLM, LocalAI)

这些适配器专门用于连接本地部署的大模型。大多数本地框架都提供 OpenAI 兼容接口。

依赖：pip install openai>=1.0
"""

from __future__ import annotations

from typing import Optional
from .openai import OpenAIProvider


class LocalProvider(OpenAIProvider):
    """
    通用的本地/自建 OpenAI 兼容 API 适配器。
    
    适用于：vLLM, LocalAI, FastChat, TGI 等。
    """
    def __init__(
        self,
        base_url: str,
        api_key: str = "not-needed",
        model: str = "default",
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )


class LMStudioProvider(OpenAIProvider):
    """
    LM Studio 专用适配器。
    默认地址：http://localhost:1234/v1
    官网：https://lmstudio.ai/
    """
    def __init__(
        self,
        model: str = "default",
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "lm-studio",
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )


class OllamaProvider(OpenAIProvider):
    """
    Ollama 专用适配器。
    默认地址：http://localhost:11434/v1
    官网：https://ollama.com/
    """
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )
