"""
Onion Core - 统一错误码定义

错误码格式：ONI-<类别><编号>

类别：
  S  - Security（安全拦截）
  R  - Rate Limit（限流）
  C  - Circuit Breaker（熔断）
  P  - Provider（LLM 调用失败）
  M  - Middleware（中间件执行错误）
  V  - Validation（参数/配置校验）
  T  - Timeout（超时）
  F  - Fallback（降级/备用策略）
  I  - Internal（内部错误）

错误码范围：
  100-199  Security
  200-299  Rate Limit
  300-399  Circuit Breaker
  400-499  Provider
  500-599  Middleware
  600-699  Validation
  700-799  Timeout
  800-899  Fallback
  900-999  Internal
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import RetryOutcome

# 为避免循环导入，运行时直接使用 models 模块
def _get_retry_outcome():
    from .models import RetryOutcome
    return RetryOutcome


# ── 错误码枚举 ─────────────────────────────────────────────────────────────────

class ErrorCode(StrEnum):
    """
    统一错误码。

    每个错误码对应一个语义明确的错误场景，便于日志检索、告警配置和客户端处理。
    """

    # Security (100-199)
    SECURITY_BLOCKED_KEYWORD = "ONI-S100"
    SECURITY_PII_DETECTED = "ONI-S101"
    SECURITY_PROMPT_INJECTION = "ONI-S102"
    SECURITY_FORBIDDEN_TOOL = "ONI-S103"

    # Rate Limit (200-299)
    RATE_LIMIT_EXCEEDED = "ONI-R200"
    RATE_LIMIT_WINDOW_FULL = "ONI-R201"

    # Circuit Breaker (300-399)
    CIRCUIT_OPEN = "ONI-C300"
    CIRCUIT_TRIPPED = "ONI-C301"

    # Provider (400-499)
    PROVIDER_AUTH_FAILED = "ONI-P400"
    PROVIDER_QUOTA_EXCEEDED = "ONI-P401"
    PROVIDER_MODEL_NOT_FOUND = "ONI-P402"
    PROVIDER_CONTENT_FILTER = "ONI-P403"
    PROVIDER_CONTEXT_OVERFLOW = "ONI-P404"
    PROVIDER_INVALID_REQUEST = "ONI-P405"

    # Middleware (500-599)
    MIDDLEWARE_REQUEST_FAILED = "ONI-M500"
    MIDDLEWARE_RESPONSE_FAILED = "ONI-M501"
    MIDDLEWARE_STREAM_FAILED = "ONI-M502"
    MIDDLEWARE_TIMEOUT = "ONI-M503"
    MIDDLEWARE_CHAIN_ABORTED = "ONI-M504"

    # Validation (600-699)
    VALIDATION_INVALID_CONFIG = "ONI-V600"
    VALIDATION_INVALID_MESSAGE = "ONI-V601"
    VALIDATION_INVALID_TOOL_CALL = "ONI-V602"
    VALIDATION_INVALID_CONTEXT = "ONI-V603"

    # Timeout (700-799)
    TIMEOUT_PROVIDER = "ONI-T700"
    TIMEOUT_MIDDLEWARE = "ONI-T701"
    TIMEOUT_TOTAL_PIPELINE = "ONI-T702"

    # Fallback (800-899)
    FALLBACK_TRIGGERED = "ONI-F800"
    FALLBACK_EXHAUSTED = "ONI-F801"
    FALLBACK_PROVIDER_FAILED = "ONI-F802"

    # Internal (900-999)
    INTERNAL_UNEXPECTED = "ONI-I900"
    INTERNAL_NOT_IMPLEMENTED = "ONI-I901"
    INTERNAL_STATE_CORRUPT = "ONI-I902"


# ── 错误码 → 默认消息映射 ─────────────────────────────────────────────────────

ERROR_MESSAGES: dict[ErrorCode, str] = {
    # Security
    ErrorCode.SECURITY_BLOCKED_KEYWORD: "Request blocked: blocked keyword detected in input",
    ErrorCode.SECURITY_PII_DETECTED: "Request blocked: PII (Personally Identifiable Information) detected in input",
    ErrorCode.SECURITY_PROMPT_INJECTION: "Request blocked: potential prompt injection detected",
    ErrorCode.SECURITY_FORBIDDEN_TOOL: "Request blocked: tool call forbidden by security policy",

    # Rate Limit
    ErrorCode.RATE_LIMIT_EXCEEDED: "Rate limit exceeded for current API key",
    ErrorCode.RATE_LIMIT_WINDOW_FULL: "Rate limit window full, please retry later",

    # Circuit Breaker
    ErrorCode.CIRCUIT_OPEN: "Circuit breaker is OPEN, provider calls are blocked",
    ErrorCode.CIRCUIT_TRIPPED: "Circuit breaker tripped due to consecutive failures",

    # Provider
    ErrorCode.PROVIDER_AUTH_FAILED: "Provider authentication failed: invalid API key or token",
    ErrorCode.PROVIDER_QUOTA_EXCEEDED: "Provider quota exceeded, please check billing",
    ErrorCode.PROVIDER_MODEL_NOT_FOUND: "Requested model not found or not accessible",
    ErrorCode.PROVIDER_CONTENT_FILTER: "Provider rejected content due to content filter policy",
    ErrorCode.PROVIDER_CONTEXT_OVERFLOW: "Request exceeds model context window limit",
    ErrorCode.PROVIDER_INVALID_REQUEST: "Invalid request sent to provider (malformed parameters)",

    # Middleware
    ErrorCode.MIDDLEWARE_REQUEST_FAILED: "Middleware failed during request processing phase",
    ErrorCode.MIDDLEWARE_RESPONSE_FAILED: "Middleware failed during response processing phase",
    ErrorCode.MIDDLEWARE_STREAM_FAILED: "Middleware failed during stream chunk processing",
    ErrorCode.MIDDLEWARE_TIMEOUT: "Middleware execution timed out",
    ErrorCode.MIDDLEWARE_CHAIN_ABORTED: "Middleware chain aborted: a middleware returned None",

    # Validation
    ErrorCode.VALIDATION_INVALID_CONFIG: "Invalid configuration provided",
    ErrorCode.VALIDATION_INVALID_MESSAGE: "Invalid message format in conversation history",
    ErrorCode.VALIDATION_INVALID_TOOL_CALL: "Invalid tool call structure",
    ErrorCode.VALIDATION_INVALID_CONTEXT: "Invalid or missing required context fields",

    # Timeout
    ErrorCode.TIMEOUT_PROVIDER: "Provider API call timed out",
    ErrorCode.TIMEOUT_MIDDLEWARE: "Middleware execution exceeded timeout",
    ErrorCode.TIMEOUT_TOTAL_PIPELINE: "Total pipeline execution exceeded timeout",

    # Fallback
    ErrorCode.FALLBACK_TRIGGERED: "Primary provider failed, switching to fallback provider",
    ErrorCode.FALLBACK_EXHAUSTED: "All providers (primary + fallbacks) failed",
    ErrorCode.FALLBACK_PROVIDER_FAILED: "Fallback provider call failed",

    # Internal
    ErrorCode.INTERNAL_UNEXPECTED: "An unexpected internal error occurred",
    ErrorCode.INTERNAL_NOT_IMPLEMENTED: "Requested feature is not yet implemented",
    ErrorCode.INTERNAL_STATE_CORRUPT: "Internal state corruption detected",
}


# ── 错误码 → 重试策略映射 ─────────────────────────────────────────────────────
# RETRY   = 可重试（瞬时故障，指数退避）
# FALLBACK = 不可重试但可切换备用 Provider
# FATAL    = 立即抛出，不重试，不 Fallback
#
# 使用字符串值避免循环导入，运行时通过 _resolve_retry_outcome() 转为枚举。

_ERROR_RETRY_STR: dict[ErrorCode, str] = {
    # Security → FATAL（安全拦截不应重试）
    ErrorCode.SECURITY_BLOCKED_KEYWORD: "fatal",
    ErrorCode.SECURITY_PII_DETECTED: "fatal",
    ErrorCode.SECURITY_PROMPT_INJECTION: "fatal",
    ErrorCode.SECURITY_FORBIDDEN_TOOL: "fatal",

    # Rate Limit → FALLBACK（可尝试备用 Provider 或等待）
    ErrorCode.RATE_LIMIT_EXCEEDED: "fallback",
    ErrorCode.RATE_LIMIT_WINDOW_FULL: "fallback",

    # Circuit Breaker → FALLBACK（跳过当前 Provider）
    ErrorCode.CIRCUIT_OPEN: "fallback",
    ErrorCode.CIRCUIT_TRIPPED: "fallback",

    # Provider → 区分处理
    ErrorCode.PROVIDER_AUTH_FAILED: "fatal",
    ErrorCode.PROVIDER_QUOTA_EXCEEDED: "fatal",
    ErrorCode.PROVIDER_MODEL_NOT_FOUND: "fatal",
    ErrorCode.PROVIDER_CONTENT_FILTER: "fatal",
    ErrorCode.PROVIDER_CONTEXT_OVERFLOW: "fatal",
    ErrorCode.PROVIDER_INVALID_REQUEST: "fatal",

    # Middleware → 根据 is_mandatory 决定（此处为默认，实际由 Pipeline 判断）
    ErrorCode.MIDDLEWARE_REQUEST_FAILED: "retry",
    ErrorCode.MIDDLEWARE_RESPONSE_FAILED: "retry",
    ErrorCode.MIDDLEWARE_STREAM_FAILED: "retry",
    ErrorCode.MIDDLEWARE_TIMEOUT: "retry",
    ErrorCode.MIDDLEWARE_CHAIN_ABORTED: "fatal",

    # Validation → FATAL（参数错误不可重试）
    ErrorCode.VALIDATION_INVALID_CONFIG: "fatal",
    ErrorCode.VALIDATION_INVALID_MESSAGE: "fatal",
    ErrorCode.VALIDATION_INVALID_TOOL_CALL: "fatal",
    ErrorCode.VALIDATION_INVALID_CONTEXT: "fatal",

    # Timeout → RETRY（瞬时超时）
    ErrorCode.TIMEOUT_PROVIDER: "retry",
    ErrorCode.TIMEOUT_MIDDLEWARE: "retry",
    ErrorCode.TIMEOUT_TOTAL_PIPELINE: "fatal",

    # Fallback → FALLBACK（已经到降级阶段）
    ErrorCode.FALLBACK_TRIGGERED: "fallback",
    ErrorCode.FALLBACK_EXHAUSTED: "fatal",
    ErrorCode.FALLBACK_PROVIDER_FAILED: "fallback",

    # Internal → FATAL
    ErrorCode.INTERNAL_UNEXPECTED: "fatal",
    ErrorCode.INTERNAL_NOT_IMPLEMENTED: "fatal",
    ErrorCode.INTERNAL_STATE_CORRUPT: "fatal",
}

# 运行时缓存
_ERROR_RETRY_POLICY_CACHE: dict[ErrorCode, RetryOutcome] | None = None


def ERROR_RETRY_POLICY() -> dict[ErrorCode, RetryOutcome]:
    """延迟解析错误码到 RetryOutcome 的映射，避免循环导入。"""
    global _ERROR_RETRY_POLICY_CACHE
    if _ERROR_RETRY_POLICY_CACHE is None:
        RetryOutcome = _get_retry_outcome()  # type: ignore[name-defined]
        _ERROR_RETRY_POLICY_CACHE = {
            code: RetryOutcome(val) for code, val in _ERROR_RETRY_STR.items()
        }
    return _ERROR_RETRY_POLICY_CACHE


# ── 带错误码的异常基类 ─────────────────────────────────────────────────────────

class OnionErrorWithCode(Exception):
    """
    Onion Core 带错误码的异常基类。

    用法：
        raise OnionErrorWithCode(
            code=ErrorCode.SECURITY_PII_DETECTED,
            message="Detected email: user@example.com",
            cause=exc,
            extra={"field": "user_input", "pii_type": "email"},
        )
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        cause: Exception | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.cause = cause
        self.extra: dict[str, Any] = extra or {}
        display_msg = message or ERROR_MESSAGES.get(code, "Unknown error")
        # Extract category from error code (e.g., "S" from "ONI-S100")
        category_code = code.split("-")[1][0] if "-" in code else "UNKNOWN"
        category_name = {
            "S": "security",
            "R": "rate_limit",
            "C": "circuit_breaker",
            "P": "provider",
            "M": "middleware",
            "V": "validation",
            "T": "timeout",
            "F": "fallback",
            "I": "internal",
        }.get(category_code, "unknown")
        full_msg = f"[{code}] [{category_name}] {display_msg}"
        if cause:
            full_msg += f" (caused by: {type(cause).__name__}: {cause})"
        super().__init__(full_msg)

    @property
    def retry_outcome(self) -> RetryOutcome:
        """该错误对应的重试策略。"""
        from .models import RetryOutcome as RO
        policy = ERROR_RETRY_POLICY()
        return policy.get(self.code, RO.FATAL)

    @property
    def is_fatal(self) -> bool:
        """是否为致命错误（不可重试、不可降级）。"""
        from .models import RetryOutcome as RO
        return self.retry_outcome == RO.FATAL

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，便于日志结构化和 API 返回。"""
        return {
            "error_code": self.code,
            "error_category": self.code.split("-")[1][0] if "-" in self.code else "UNKNOWN",
            "message": str(self),
            "retry_outcome": self.retry_outcome.value,
            "is_fatal": self.is_fatal,
            "extra": self.extra,
        }


# ── 便捷工厂函数 ───────────────────────────────────────────────────────────────

def security_error(
    code: ErrorCode = ErrorCode.SECURITY_BLOCKED_KEYWORD,
    message: str | None = None,
    extra: dict[str, Any] | None = None,
) -> OnionErrorWithCode:
    """构造安全类错误。"""
    return OnionErrorWithCode(code=code, message=message, extra=extra)


def provider_error(
    code: ErrorCode = ErrorCode.PROVIDER_INVALID_REQUEST,
    message: str | None = None,
    cause: Exception | None = None,
    extra: dict[str, Any] | None = None,
) -> OnionErrorWithCode:
    """构造 Provider 类错误。"""
    return OnionErrorWithCode(code=code, message=message, cause=cause, extra=extra)


def fallback_error(
    code: ErrorCode = ErrorCode.FALLBACK_EXHAUSTED,
    message: str | None = None,
    cause: Exception | None = None,
    extra: dict[str, Any] | None = None,
) -> OnionErrorWithCode:
    """构造降级相关错误。"""
    return OnionErrorWithCode(code=code, message=message, cause=cause, extra=extra)
