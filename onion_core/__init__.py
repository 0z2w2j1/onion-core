"""
Onion Core — Agent 中间件框架

公开 API：
    from onion_core import Pipeline, BaseMiddleware, AgentContext, Message
    from onion_core import LLMProvider, LLMResponse, EchoProvider
    from onion_core import OnionError, SecurityException, RateLimitExceeded, RetryPolicy
    from onion_core import ErrorCode, OnionErrorWithCode
    from onion_core.middlewares import ObservabilityMiddleware, SafetyGuardrailMiddleware, ContextWindowMiddleware
"""

from importlib.metadata import PackageNotFoundError, version

from .agent import AgentLoop, AgentLoopError
from .base import BaseMiddleware
from .config import (
    ConcurrencyConfig,
    ContextWindowConfig,
    ObservabilityConfig,
    OnionConfig,
    PipelineConfig,
    SafetyConfig,
)
from .error_codes import (
    ERROR_MESSAGES,
    ERROR_RETRY_POLICY,
    ErrorCode,
    OnionErrorWithCode,
    fallback_error,
    provider_error,
    security_error,
)
from .health_server import HealthServer, start_health_server
from .models import (
    AgentContext,
    CacheHitException,
    FinishReason,
    LLMResponse,
    Message,
    MessageRole,
    MiddlewareEvent,
    # 异常基类与 RetryPolicy
    OnionError,
    ProviderError,
    RateLimitExceeded,
    RetryOutcome,
    RetryPolicy,
    SecurityException,
    StreamChunk,
    ToolCall,
    ToolResult,
    UsageStats,
    ValidationError,
)
from .pipeline import MiddlewareManager, Pipeline
from .provider import EchoProvider, LLMProvider

try:
    __version__ = version("onion-core")
except PackageNotFoundError:
    __version__ = "0.7.4"

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
    "ValidationError",
    "CacheHitException",
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
    "ConcurrencyConfig",
    "SafetyConfig",
    "ContextWindowConfig",
    "ObservabilityConfig",
    "AgentLoop",
    "AgentLoopError",
    # 健康检查服务器
    "HealthServer",
    "start_health_server",
    # 版本
    "__version__",
]
