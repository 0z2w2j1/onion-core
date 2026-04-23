"""
Onion Core — Agent 中间件框架

公开 API：
    from onion_core import Pipeline, BaseMiddleware, AgentContext, Message
    from onion_core import LLMProvider, LLMResponse, EchoProvider
    from onion_core import OnionError, SecurityException, RateLimitExceeded, RetryPolicy
    from onion_core import ErrorCode, OnionErrorWithCode
    from onion_core.middlewares import ObservabilityMiddleware, SafetyGuardrailMiddleware, ContextWindowMiddleware
"""

from .models import (
    AgentContext,
    Message,
    MessageRole,
    LLMResponse,
    StreamChunk,
    ToolCall,
    ToolResult,
    UsageStats,
    MiddlewareEvent,
    FinishReason,
    # 异常基类与 RetryPolicy
    OnionError,
    SecurityException,
    RateLimitExceeded,
    ProviderError,
    RetryPolicy,
    RetryOutcome,
)
from .error_codes import (
    ErrorCode,
    OnionErrorWithCode,
    ERROR_MESSAGES,
    ERROR_RETRY_POLICY,
    security_error,
    provider_error,
    fallback_error,
)
from .base import BaseMiddleware
from .provider import LLMProvider, EchoProvider
from .pipeline import Pipeline, MiddlewareManager
from .config import OnionConfig, PipelineConfig, SafetyConfig, ContextWindowConfig, ObservabilityConfig
from .agent import AgentLoop, AgentLoopError

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("onion-core")
except PackageNotFoundError:
    __version__ = "0.5.0"

__all__ = [
    # 核心
    "Pipeline",
    "MiddlewareManager",
    "BaseMiddleware",
    # Provider
    "LLMProvider",
    "EchoProvider",
    # 模型
    "AgentContext",
    "Message",
    "MessageRole",
    "LLMResponse",
    "StreamChunk",
    "ToolCall",
    "ToolResult",
    "UsageStats",
    "MiddlewareEvent",
    "FinishReason",
    # 异常与重试策略
    "OnionError",
    "SecurityException",
    "RateLimitExceeded",
    "ProviderError",
    "RetryPolicy",
    "RetryOutcome",
    # 错误码（新增）
    "ErrorCode",
    "OnionErrorWithCode",
    "ERROR_MESSAGES",
    "ERROR_RETRY_POLICY",
    "security_error",
    "provider_error",
    "fallback_error",
    # 配置
    "OnionConfig",
    "PipelineConfig",
    "SafetyConfig",
    "ContextWindowConfig",
    "ObservabilityConfig",
    "AgentLoop",
    "AgentLoopError",
    # 版本
    "__version__",
]
