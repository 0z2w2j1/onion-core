"""Tests for error_codes module."""

from __future__ import annotations

from onion_core.error_codes import (
    ERROR_MESSAGES,
    ERROR_RETRY_POLICY,
    ErrorCode,
    OnionErrorWithCode,
    fallback_error,
    provider_error,
    security_error,
)


class TestErrorCodeEnum:
    def test_error_code_values(self):
        assert ErrorCode.SECURITY_BLOCKED_KEYWORD.value == "ONI-S100"
        assert ErrorCode.RATE_LIMIT_EXCEEDED.value == "ONI-R200"
        assert ErrorCode.CIRCUIT_OPEN.value == "ONI-C300"
        assert ErrorCode.PROVIDER_AUTH_FAILED.value == "ONI-P400"
        assert ErrorCode.MIDDLEWARE_REQUEST_FAILED.value == "ONI-M500"
        assert ErrorCode.VALIDATION_INVALID_CONFIG.value == "ONI-V600"
        assert ErrorCode.TIMEOUT_PROVIDER.value == "ONI-T700"
        assert ErrorCode.FALLBACK_TRIGGERED.value == "ONI-F800"
        assert ErrorCode.INTERNAL_UNEXPECTED.value == "ONI-I900"


class TestErrorMessages:
    def test_error_messages_mapping(self):
        assert len(ERROR_MESSAGES) > 0
        assert ErrorCode.SECURITY_PII_DETECTED in ERROR_MESSAGES
        msg = ERROR_MESSAGES[ErrorCode.SECURITY_PII_DETECTED]
        assert "PII" in msg

    def test_get_message_for_code(self):
        assert "detected" in ERROR_MESSAGES[ErrorCode.SECURITY_PROMPT_INJECTION].lower()


class TestRetryPolicy:
    def test_retry_policy_contains_all_codes(self):
        policy = ERROR_RETRY_POLICY()
        assert len(policy) >= len(ErrorCode)
        for code in ErrorCode:
            assert code in policy

    def test_retry_outcome_values(self):
        policy = ERROR_RETRY_POLICY()
        from onion_core.models import RetryOutcome
        for outcome in policy.values():
            assert outcome in (RetryOutcome.RETRY, RetryOutcome.FALLBACK, RetryOutcome.FATAL)


class TestOnionErrorWithCode:
    def test_basic_error(self):
        err = OnionErrorWithCode(code=ErrorCode.SECURITY_BLOCKED_KEYWORD)
        assert err.code == ErrorCode.SECURITY_BLOCKED_KEYWORD
        assert "security" in str(err).lower()

    def test_error_with_custom_message(self):
        err = OnionErrorWithCode(
            code=ErrorCode.SECURITY_PII_DETECTED,
            message="Custom PII message"
        )
        assert "Custom PII message" in str(err)

    def test_error_with_cause(self):
        cause = ValueError("original error")
        err = OnionErrorWithCode(
            code=ErrorCode.PROVIDER_AUTH_FAILED,
            cause=cause
        )
        assert err.cause is cause
        assert "ValueError" in str(err)

    def test_error_with_extra(self):
        extra = {"field": "email", "detected": "test@example.com"}
        err = OnionErrorWithCode(
            code=ErrorCode.SECURITY_PII_DETECTED,
            extra=extra
        )
        assert err.extra == extra

    def test_retry_outcome_property(self):
        err = OnionErrorWithCode(code=ErrorCode.TIMEOUT_PROVIDER)
        from onion_core.models import RetryOutcome
        assert err.retry_outcome == RetryOutcome.RETRY

    def test_is_fatal_property(self):
        err_fatal = OnionErrorWithCode(code=ErrorCode.VALIDATION_INVALID_CONFIG)
        assert err_fatal.is_fatal

        err_retry = OnionErrorWithCode(code=ErrorCode.TIMEOUT_PROVIDER)
        assert not err_retry.is_fatal

    def test_to_dict(self):
        err = OnionErrorWithCode(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message="rate limited",
            extra={"key": "value"}
        )
        d = err.to_dict()
        assert d["error_code"] == ErrorCode.RATE_LIMIT_EXCEEDED.value
        assert "rate" in d["message"].lower()
        assert d["retry_outcome"] in ("retry", "fallback", "fatal")
        assert d["is_fatal"] in (True, False)
        assert d["extra"]["key"] == "value"

    def test_category_extraction(self):
        err = OnionErrorWithCode(code=ErrorCode.RATE_LIMIT_EXCEEDED)
        d = err.to_dict()
        assert d["error_category"] == "R"


class TestFactoryFunctions:
    def test_security_error(self):
        err = security_error(
            code=ErrorCode.SECURITY_PII_DETECTED,
            message="email detected",
            extra={"email": "x@y.com"}
        )
        assert err.code == ErrorCode.SECURITY_PII_DETECTED
        assert "email detected" in str(err)

    def test_provider_error(self):
        cause = RuntimeError("timeout")
        err = provider_error(
            code=ErrorCode.PROVIDER_QUOTA_EXCEEDED,
            message="quota exceeded",
            cause=cause,
            extra={"org": "myorg"}
        )
        assert err.code == ErrorCode.PROVIDER_QUOTA_EXCEEDED
        assert err.cause is cause
        assert err.extra["org"] == "myorg"

    def test_fallback_error(self):
        err = fallback_error(
            code=ErrorCode.FALLBACK_EXHAUSTED,
            message="all providers failed"
        )
        assert err.code == ErrorCode.FALLBACK_EXHAUSTED
        assert "all providers failed" in str(err)