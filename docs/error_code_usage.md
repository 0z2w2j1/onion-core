# Onion Core - Error Code Usage Guide

> Version: v0.5.0 | Updated: 2026-04-24

## 1. Quick Start

### 1.1 Raising Exceptions (New Way)

```python
from onion_core import OnionErrorWithCode, ErrorCode

# Basic usage
raise OnionErrorWithCode(
    code=ErrorCode.SECURITY_PII_DETECTED,
    message="Detected email address in user input",
    extra={"field": "user_message", "pii_type": "email"},
)
```

### 1.2 Using Factory Functions

```python
from onion_core import security_error, provider_error, fallback_error

# Security errors
raise security_error(
    code=ErrorCode.SECURITY_BLOCKED_KEYWORD,
    message="Blocked keyword: 'ignore previous instructions'",
    extra={"keyword": "ignore previous instructions"},
)

# Provider errors
raise provider_error(
    code=ErrorCode.PROVIDER_AUTH_FAILED,
    message="Invalid API key",
    cause=exc,  # Original exception
)

# Fallback errors
raise fallback_error(
    code=ErrorCode.FALLBACK_EXHAUSTED,
    message="All providers failed",
    cause=last_exception,
)
```

### 1.3 Backward Compatibility (Old Way Still Works)

```python
from onion_core import SecurityException, RateLimitExceeded

# Original exception classes still work
raise SecurityException("Blocked: PII detected")
raise RateLimitExceeded("Rate limit exceeded")
```

---

## 2. Error Code Categories

| Category | Prefix | Description | Retry Strategy |
|------|------|------|----------|
| Security | `ONI-S` | Security blocks (PII, injection attacks) | FATAL (no retry) |
| Rate Limit | `ONI-R` | API rate limits | FALLBACK (switch backup) |
| Circuit Breaker | `ONI-C` | Circuit breaker status | FALLBACK (skip current) |
| Provider | `ONI-P` | LLM Provider call errors | Varies |
| Middleware | `ONI-M` | Middleware execution errors | RETRY (can retry) |
| Validation | `ONI-V` | Parameter/config validation errors | FATAL (no retry) |
| Timeout | `ONI-T` | Timeout errors | RETRY (can retry) |
| Fallback | `ONI-F` | Degradation related | FALLBACK/FATAL |
| Internal | `ONI-I` | Internal errors | FATAL (no retry) |

---

## 3. Using Error Codes in Middleware

```python
from onion_core import BaseMiddleware, ErrorCode, OnionErrorWithCode
from onion_core.models import AgentContext, LLMResponse

class MySecurityMiddleware(BaseMiddleware):
    priority = 200

    async def process_request(self, context: AgentContext) -> AgentContext:
        user_msg = self._get_last_user_message(context)
        if self._contains_pii(user_msg):
            raise OnionErrorWithCode(
                code=ErrorCode.SECURITY_PII_DETECTED,
                message="PII detected in user input",
                extra={
                    "session_id": context.session_id,
                    "pii_type": "email",
                },
            )
        return context

    def _contains_pii(self, text: str) -> bool:
        # Implement PII detection logic
        return False
```

---

## 4. Using Error Codes in Provider

```python
from onion_core import LLMProvider, ErrorCode, provider_error
from onion_core.models import AgentContext, LLMResponse

class MyProvider(LLMProvider):
    async def complete(self, context: AgentContext) -> LLMResponse:
        try:
            response = await self._call_api(context)
            return response
        except AuthError as exc:
            raise provider_error(
                code=ErrorCode.PROVIDER_AUTH_FAILED,
                message="Authentication failed: invalid API key",
                cause=exc,
                extra={"provider": self.__class__.__name__},
            ) from exc
        except QuotaExceededError as exc:
            raise provider_error(
                code=ErrorCode.PROVIDER_QUOTA_EXCEEDED,
                message="API quota exceeded",
                cause=exc,
            ) from exc
```

---

## 5. Error Serialization & Logging

### 5.1 Serializing to Dictionary

```python
try:
    response = await pipeline.run(context)
except OnionErrorWithCode as exc:
    error_dict = exc.to_dict()
    # {
    #     "error_code": "ONI-S101",
    #     "error_category": "S",
    #     "message": "[ONI-S101] Request blocked: PII detected",
    #     "retry_outcome": "fatal",
    #     "is_fatal": True,
    #     "extra": {"field": "user_message"},
    # }
```

### 5.2 Structured Logging

```python
import logging
import json

logger = logging.getLogger("my_app")

try:
    response = await pipeline.run(context)
except OnionErrorWithCode as exc:
    logger.error(
        "Request failed",
        extra={"error": exc.to_dict()},
    )
    # Outputs structured log:
    # {"error_code": "ONI-S101", "error_category": "S", "message": "...", ...}
```

---

## 6. HTTP API Error Response Example

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from onion_core import OnionErrorWithCode, ErrorCode

app = FastAPI()

@app.exception_handler(OnionErrorWithCode)
async def onion_error_handler(request: Request, exc: OnionErrorWithCode):
    status_code = 400 if exc.code.startswith("ONI-S") else 502
    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.to_dict(),
        },
    )
```

---

## 7. Custom Error Codes

To extend with custom error codes:

```python
from enum import Enum
from onion_core.error_codes import ERROR_MESSAGES, ERROR_RETRY_POLICY, RetryOutcome

class MyErrorCode(str, Enum):
    CUSTOM_BUSINESS_RULE = "ONI-B100"  # B = Business

# Register message and retry strategy
ERROR_MESSAGES[MyErrorCode.CUSTOM_BUSINESS_RULE] = "Business rule violation"
ERROR_RETRY_POLICY()[MyErrorCode.CUSTOM_BUSINESS_RULE] = RetryOutcome.FATAL
```

---

## 8. Error Code Reference Table

| Error Code | Name | Retry Strategy | Description |
|-----------|------|----------|------|
| `ONI-S100` | SECURITY_BLOCKED_KEYWORD | FATAL | Keyword blocked |
| `ONI-S101` | SECURITY_PII_DETECTED | FATAL | PII detected |
| `ONI-S102` | SECURITY_PROMPT_INJECTION | FATAL | Prompt injection |
| `ONI-S103` | SECURITY_FORBIDDEN_TOOL | FATAL | Tool call forbidden |
| `ONI-R200` | RATE_LIMIT_EXCEEDED | FALLBACK | Rate limit exceeded |
| `ONI-R201` | RATE_LIMIT_WINDOW_FULL | FALLBACK | Rate limit window full |
| `ONI-C300` | CIRCUIT_OPEN | FALLBACK | Circuit breaker open |
| `ONI-C301` | CIRCUIT_TRIPPED | FALLBACK | Circuit breaker tripped |
| `ONI-P400` | PROVIDER_AUTH_FAILED | FATAL | Auth failed |
| `ONI-P401` | PROVIDER_QUOTA_EXCEEDED | FATAL | Quota exhausted |
| `ONI-P402` | PROVIDER_MODEL_NOT_FOUND | FATAL | Model not found |
| `ONI-P403` | PROVIDER_CONTENT_FILTER | FATAL | Content filtered |
| `ONI-P404` | PROVIDER_CONTEXT_OVERFLOW | FATAL | Context overflow |
| `ONI-P405` | PROVIDER_INVALID_REQUEST | FATAL | Invalid request |
| `ONI-M500` | MIDDLEWARE_REQUEST_FAILED | RETRY | Middleware request phase failed |
| `ONI-M501` | MIDDLEWARE_RESPONSE_FAILED | RETRY | Middleware response phase failed |
| `ONI-M502` | MIDDLEWARE_STREAM_FAILED | RETRY | Middleware stream processing failed |
| `ONI-M503` | MIDDLEWARE_TIMEOUT | RETRY | Middleware timeout |
| `ONI-M504` | MIDDLEWARE_CHAIN_ABORTED | FATAL | Middleware chain aborted |
| `ONI-V600` | VALIDATION_INVALID_CONFIG | FATAL | Invalid config |
| `ONI-V601` | VALIDATION_INVALID_MESSAGE | FATAL | Invalid message format |
| `ONI-V602` | VALIDATION_INVALID_TOOL_CALL | FATAL | Invalid tool call |
| `ONI-V603` | VALIDATION_INVALID_CONTEXT | FATAL | Invalid context |
| `ONI-T700` | TIMEOUT_PROVIDER | RETRY | Provider timeout |
| `ONI-T701` | TIMEOUT_MIDDLEWARE | RETRY | Middleware timeout |
| `ONI-T702` | TIMEOUT_TOTAL_PIPELINE | FATAL | Pipeline total timeout |
| `ONI-F800` | FALLBACK_TRIGGERED | FALLBACK | Degradation triggered |
| `ONI-F801` | FALLBACK_EXHAUSTED | FATAL | All providers failed |
| `ONI-F802` | FALLBACK_PROVIDER_FAILED | FALLBACK | Fallback failed |
| `ONI-I900` | INTERNAL_UNEXPECTED | FATAL | Internal error |
| `ONI-I901` | INTERNAL_NOT_IMPLEMENTED | FATAL | Not implemented |
| `ONI-I902` | INTERNAL_STATE_CORRUPT | FATAL | State corrupted |

---

# Onion Core - 错误码使用指南

> 版本：v0.5.0 | 更新日期：2026-04-24

## 1. 快速开始

### 1.1 抛出异常（新方式）

```python
from onion_core import OnionErrorWithCode, ErrorCode

# 基础用法
raise OnionErrorWithCode(
    code=ErrorCode.SECURITY_PII_DETECTED,
    message="Detected email address in user input",
    extra={"field": "user_message", "pii_type": "email"},
)
```

### 1.2 使用工厂函数

```python
from onion_core import security_error, provider_error, fallback_error

# 安全类错误
raise security_error(
    code=ErrorCode.SECURITY_BLOCKED_KEYWORD,
    message="Blocked keyword: 'ignore previous instructions'",
    extra={"keyword": "ignore previous instructions"},
)

# Provider 类错误
raise provider_error(
    code=ErrorCode.PROVIDER_AUTH_FAILED,
    message="Invalid API key",
    cause=exc,  # 原始异常
)

# Fallback 类错误
raise fallback_error(
    code=ErrorCode.FALLBACK_EXHAUSTED,
    message="All providers failed",
    cause=last_exception,
)
```

### 1.3 向后兼容（旧方式仍然可用）

```python
from onion_core import SecurityException, RateLimitExceeded

# 原有异常类仍然可用
raise SecurityException("Blocked: PII detected")
raise RateLimitExceeded("Rate limit exceeded")
```

---

## 2. 错误码分类

| 类别 | 前缀 | 说明 | 重试策略 |
|------|------|------|----------|
| Security | `ONI-S` | 安全拦截（PII、注入攻击等） | FATAL（不重试） |
| Rate Limit | `ONI-R` | API 限流 | FALLBACK（切换备用） |
| Circuit Breaker | `ONI-C` | 熔断器状态 | FALLBACK（跳过当前） |
| Provider | `ONI-P` | LLM Provider 调用错误 | 视具体错误而定 |
| Middleware | `ONI-M` | 中间件执行错误 | RETRY（可重试） |
| Validation | `ONI-V` | 参数/配置校验错误 | FATAL（不重试） |
| Timeout | `ONI-T` | 超时错误 | RETRY（可重试） |
| Fallback | `ONI-F` | 降级相关错误 | FALLBACK/FATAL |
| Internal | `ONI-I` | 内部错误 | FATAL（不重试） |

---

## 3. 在中间件中使用错误码

```python
from onion_core import BaseMiddleware, ErrorCode, OnionErrorWithCode
from onion_core.models import AgentContext, LLMResponse

class MySecurityMiddleware(BaseMiddleware):
    priority = 200

    async def process_request(self, context: AgentContext) -> AgentContext:
        user_msg = self._get_last_user_message(context)
        if self._contains_pii(user_msg):
            raise OnionErrorWithCode(
                code=ErrorCode.SECURITY_PII_DETECTED,
                message="PII detected in user input",
                extra={
                    "session_id": context.session_id,
                    "pii_type": "email",
                },
            )
        return context

    def _contains_pii(self, text: str) -> bool:
        # 实现 PII 检测逻辑
        return False
```

---

## 4. 在 Provider 中使用错误码

```python
from onion_core import LLMProvider, ErrorCode, provider_error
from onion_core.models import AgentContext, LLMResponse

class MyProvider(LLMProvider):
    async def complete(self, context: AgentContext) -> LLMResponse:
        try:
            response = await self._call_api(context)
            return response
        except AuthError as exc:
            raise provider_error(
                code=ErrorCode.PROVIDER_AUTH_FAILED,
                message="Authentication failed: invalid API key",
                cause=exc,
                extra={"provider": self.__class__.__name__},
            ) from exc
        except QuotaExceededError as exc:
            raise provider_error(
                code=ErrorCode.PROVIDER_QUOTA_EXCEEDED,
                message="API quota exceeded",
                cause=exc,
            ) from exc
```

---

## 5. 错误序列化与日志

### 5.1 序列化为字典

```python
try:
    response = await pipeline.run(context)
except OnionErrorWithCode as exc:
    error_dict = exc.to_dict()
    # {
    #     "error_code": "ONI-S101",
    #     "error_category": "S",
    #     "message": "[ONI-S101] Request blocked: PII detected",
    #     "retry_outcome": "fatal",
    #     "is_fatal": True,
    #     "extra": {"field": "user_message"},
    # }
```

### 5.2 结构化日志

```python
import logging
import json

logger = logging.getLogger("my_app")

try:
    response = await pipeline.run(context)
except OnionErrorWithCode as exc:
    logger.error(
        "Request failed",
        extra={"error": exc.to_dict()},
    )
    # 输出结构化日志：
    # {"error_code": "ONI-S101", "error_category": "S", "message": "...", ...}
```

---

## 6. HTTP API 错误响应示例

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from onion_core import OnionErrorWithCode, ErrorCode

app = FastAPI()

@app.exception_handler(OnionErrorWithCode)
async def onion_error_handler(request: Request, exc: OnionErrorWithCode):
    status_code = 400 if exc.code.startswith("ONI-S") else 502
    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.to_dict(),
        },
    )
```

---

## 7. 自定义错误码

如需扩展自定义错误码，可在项目中定义扩展枚举：

```python
from enum import Enum
from onion_core.error_codes import ERROR_MESSAGES, ERROR_RETRY_POLICY, RetryOutcome

class MyErrorCode(str, Enum):
    CUSTOM_BUSINESS_RULE = "ONI-B100"  # B = Business

# 注册消息和重试策略
ERROR_MESSAGES[MyErrorCode.CUSTOM_BUSINESS_RULE] = "Business rule violation"
ERROR_RETRY_POLICY()[MyErrorCode.CUSTOM_BUSINESS_RULE] = RetryOutcome.FATAL
```

---

## 8. 错误码参考表

| 错误码 | 名称 | 重试策略 | 说明 |
|--------|------|----------|------|
| `ONI-S100` | SECURITY_BLOCKED_KEYWORD | FATAL | 关键词拦截 |
| `ONI-S101` | SECURITY_PII_DETECTED | FATAL | PII 检测 |
| `ONI-S102` | SECURITY_PROMPT_INJECTION | FATAL | 提示词注入 |
| `ONI-S103` | SECURITY_FORBIDDEN_TOOL | FATAL | 工具调用禁止 |
| `ONI-R200` | RATE_LIMIT_EXCEEDED | FALLBACK | 限流 |
| `ONI-R201` | RATE_LIMIT_WINDOW_FULL | FALLBACK | 限流窗口满 |
| `ONI-C300` | CIRCUIT_OPEN | FALLBACK | 熔断器打开 |
| `ONI-C301` | CIRCUIT_TRIPPED | FALLBACK | 熔断器触发 |
| `ONI-P400` | PROVIDER_AUTH_FAILED | FATAL | 认证失败 |
| `ONI-P401` | PROVIDER_QUOTA_EXCEEDED | FATAL | 配额耗尽 |
| `ONI-P402` | PROVIDER_MODEL_NOT_FOUND | FATAL | 模型不存在 |
| `ONI-P403` | PROVIDER_CONTENT_FILTER | FATAL | 内容过滤 |
| `ONI-P404` | PROVIDER_CONTEXT_OVERFLOW | FATAL | 上下文超限 |
| `ONI-P405` | PROVIDER_INVALID_REQUEST | FATAL | 请求格式错误 |
| `ONI-M500` | MIDDLEWARE_REQUEST_FAILED | RETRY | 中间件请求阶段失败 |
| `ONI-M501` | MIDDLEWARE_RESPONSE_FAILED | RETRY | 中间件响应阶段失败 |
| `ONI-M502` | MIDDLEWARE_STREAM_FAILED | RETRY | 中间件流处理失败 |
| `ONI-M503` | MIDDLEWARE_TIMEOUT | RETRY | 中间件超时 |
| `ONI-M504` | MIDDLEWARE_CHAIN_ABORTED | FATAL | 中间件链中断 |
| `ONI-V600` | VALIDATION_INVALID_CONFIG | FATAL | 配置无效 |
| `ONI-V601` | VALIDATION_INVALID_MESSAGE | FATAL | 消息格式无效 |
| `ONI-V602` | VALIDATION_INVALID_TOOL_CALL | FATAL | 工具调用无效 |
| `ONI-V603` | VALIDATION_INVALID_CONTEXT | FATAL | 上下文无效 |
| `ONI-T700` | TIMEOUT_PROVIDER | RETRY | Provider 超时 |
| `ONI-T701` | TIMEOUT_MIDDLEWARE | RETRY | 中间件超时 |
| `ONI-T702` | TIMEOUT_TOTAL_PIPELINE | FATAL | Pipeline 总超时 |
| `ONI-F800` | FALLBACK_TRIGGERED | FALLBACK | 触发降级 |
| `ONI-F801` | FALLBACK_EXHAUSTED | FATAL | 全部 Provider 失败 |
| `ONI-F802` | FALLBACK_PROVIDER_FAILED | FALLBACK | Fallback 失败 |
| `ONI-I900` | INTERNAL_UNEXPECTED | FATAL | 内部错误 |
| `ONI-I901` | INTERNAL_NOT_IMPLEMENTED | FATAL | 未实现 |
| `ONI-I902` | INTERNAL_STATE_CORRUPT | FATAL | 状态损坏 |
