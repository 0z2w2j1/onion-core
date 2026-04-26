# Onion Core - API Reference

> Version: 0.8.0 | Updated: 2026-04-26

This document describes every public class, function, and configuration option in the `onion_core` package.

---

## Package Exports (`onion_core.__init__`)

```python
from onion_core import (
    # Core
    Pipeline, MiddlewareManager, BaseMiddleware,
    # Provider
    LLMProvider, EchoProvider,
    # Models
    AgentContext, Message, MessageRole,
    LLMResponse, StreamChunk, ToolCall, ToolResult,
    UsageStats, MiddlewareEvent, FinishReason,
    # Errors & Retry
    OnionError, SecurityException, RateLimitExceeded,
    ProviderError, RetryPolicy, RetryOutcome,
    # Error Codes (New)
    ErrorCode, OnionErrorWithCode,
    ERROR_MESSAGES, ERROR_RETRY_POLICY,
    security_error, provider_error, fallback_error,
    # Config
    OnionConfig, PipelineConfig, SafetyConfig,
    ContextWindowConfig, ObservabilityConfig,
    # Agent
    AgentLoop, AgentLoopError,
    # Version
    __version__,
)
```

**New in v0.7.0:**
- Enhanced sync API methods with automatic event loop detection
- Response caching support via `ResponseCacheMiddleware`

---

## Module: `onion_core.models`

### Enums

#### `MessageRole`
```python
MessageRole = Literal["system", "user", "assistant", "tool"]
```

#### `FinishReason`
```python
class FinishReason(str, Enum):
    STOP = "stop"              # Normal completion
    LENGTH = "length"          # Cut off by max tokens
    TOOL_CALLS = "tool_calls"  # Model requested tool calls
    CONTENT_FILTER = "content_filter"  # Blocked by content filter
    ERROR = "error"            # Error occurred
```

#### `CircuitState`
```python
class CircuitState(str, Enum):
    CLOSED = "closed"          # Normal: requests pass through
    OPEN = "open"              # Breaker tripped: requests rejected
    HALF_OPEN = "half_open"    # Testing: limited requests allowed
```

#### `RetryOutcome`
```python
class RetryOutcome(str, Enum):
    RETRY = "retry"             # Transient failure: exponential backoff
    FALLBACK = "fallback"       # Service error: try next provider
    FATAL = "fatal"             # Fatal error: throw immediately
```

#### `MiddlewareEvent`
```python
class MiddlewareEvent(str, Enum):
    ON_REQUEST = "on_request"
    ON_RESPONSE = "on_response"
    ON_STREAM_CHUNK = "on_stream_chunk"
    ON_ERROR = "on_error"
    ON_TOOL_CALL = "on_tool_call"
    ON_TOOL_RESULT = "on_tool_result"
```

#### `ErrorCode`
```python
class ErrorCode(str, Enum):
    # Security (100-199)
    SECURITY_BLOCKED_KEYWORD   = "ONI-S100"
    SECURITY_PII_DETECTED      = "ONI-S101"
    SECURITY_PROMPT_INJECTION  = "ONI-S102"
    SECURITY_FORBIDDEN_TOOL    = "ONI-S103"
    # Rate Limit (200-299)
    RATE_LIMIT_EXCEEDED        = "ONI-R200"
    RATE_LIMIT_WINDOW_FULL     = "ONI-R201"
    # Circuit Breaker (300-399)
    CIRCUIT_OPEN               = "ONI-C300"
    CIRCUIT_TRIPPED            = "ONI-C301"
    # Provider (400-499)
    PROVIDER_AUTH_FAILED       = "ONI-P400"
    PROVIDER_QUOTA_EXCEEDED   = "ONI-P401"
    PROVIDER_MODEL_NOT_FOUND  = "ONI-P402"
    PROVIDER_CONTENT_FILTER   = "ONI-P403"
    PROVIDER_CONTEXT_OVERFLOW = "ONI-P404"
    PROVIDER_INVALID_REQUEST  = "ONI-P405"
    # Middleware (500-599)
    MIDDLEWARE_REQUEST_FAILED  = "ONI-M500"
    MIDDLEWARE_RESPONSE_FAILED = "ONI-M501"
    MIDDLEWARE_STREAM_FAILED   = "ONI-M502"
    MIDDLEWARE_TIMEOUT         = "ONI-M503"
    MIDDLEWARE_CHAIN_ABORTED  = "ONI-M504"
    # Validation (600-699)
    VALIDATION_INVALID_CONFIG  = "ONI-V600"
    VALIDATION_INVALID_MESSAGE = "ONI-V601"
    VALIDATION_INVALID_TOOL_CALL = "ONI-V602"
    VALIDATION_INVALID_CONTEXT = "ONI-V603"
    # Timeout (700-799)
    TIMEOUT_PROVIDER           = "ONI-T700"
    TIMEOUT_MIDDLEWARE         = "ONI-T701"
    TIMEOUT_TOTAL_PIPELINE    = "ONI-T702"
    # Fallback (800-899)
    FALLBACK_TRIGGERED        = "ONI-F800"
    FALLBACK_EXHAUSTED        = "ONI-F801"
    FALLBACK_PROVIDER_FAILED  = "ONI-F802"
    # Internal (900-999)
    INTERNAL_UNEXPECTED       = "ONI-I900"
    INTERNAL_NOT_IMPLEMENTED  = "ONI-I901"
    INTERNAL_STATE_CORRUPT    = "ONI-I902"
```

---

### Data Models (Pydantic)

#### `Message`
```python
class Message(BaseModel):
    role: MessageRole
    content: Union[str, List[ContentBlock]]
    name: Optional[str] = None

    @property
    def text_content(self) -> str: ...
```

#### `AgentContext`
```python
class AgentContext(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    messages: List[Message] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
```

#### `ToolCall`
```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
```

#### `ToolResult`
```python
class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    result: Optional[Union[str, Dict[str, Any], List[Any]]] = None
    error: Optional[str] = None

    @property
    def is_error(self) -> bool: ...
```

#### `UsageStats`
```python
class UsageStats(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

#### `LLMResponse`
```python
class LLMResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    finish_reason: Optional[FinishReason] = None
    usage: Optional[UsageStats] = None
    model: Optional[str] = None
    raw: Optional[Any] = None

    @property
    def has_tool_calls(self) -> bool: ...

    @property
    def is_complete(self) -> bool: ...
```

#### `StreamChunk`
```python
class StreamChunk(BaseModel):
    delta: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    finish_reason: Optional[FinishReason] = None
    index: int = 0
```

---

### Exception Classes

#### `OnionError`
```python
class OnionError(Exception):
    """Base exception for all Onion Core errors."""
```

#### `SecurityException(OnionError)`
```python
class SecurityException(OnionError):
    is_fatal: bool = True
```

#### `RateLimitExceeded(OnionError)`
```python
class RateLimitExceeded(OnionError):
    is_fatal: bool = True
```

#### `ProviderError(OnionError)`
```python
class ProviderError(OnionError):
    is_fatal: bool = False
```

#### `CircuitBreakerError(OnionError)`
```python
class CircuitBreakerError(OnionError):
    is_fatal: bool = False
```

#### `OnionErrorWithCode(Exception)` (New)
```python
class OnionErrorWithCode(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: Optional[str] = None,
        cause: Optional[Exception] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    @property
    def retry_outcome(self) -> RetryOutcome: ...

    @property
    def is_fatal(self) -> bool: ...

    def to_dict(self) -> Dict[str, Any]: ...
```

#### Retry Policy
```python
class RetryPolicy:
    def classify(self, exc: Exception) -> RetryOutcome: ...
    def is_retryable(self, exc: Exception) -> bool: ...
    def is_fatal(self, exc: Exception) -> bool: ...
    def is_chain_breaking(self, exc: Exception) -> bool: ...
```

---

## Module: `onion_core.base`

### `BaseMiddleware`
```python
class BaseMiddleware(ABC):
    priority: int = 500
    timeout: Optional[float] = None
    is_mandatory: bool = False

    @property
    def name(self) -> str: ...

    # Lifecycle
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...

    # Required (abstract)
    async def process_request(self, context: AgentContext) -> AgentContext: ...
    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse: ...

    # Optional (default: pass-through)
    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk: ...

    async def on_tool_call(
        self, context: AgentContext, tool_call: ToolCall
    ) -> ToolCall: ...

    async def on_tool_result(
        self, context: AgentContext, result: ToolResult
    ) -> ToolResult: ...

    async def on_error(
        self, context: AgentContext, error: Exception
    ) -> None: ...
```

---

## Module: `onion_core.pipeline`

### `Pipeline`
```python
class Pipeline:
    def __init__(
        self,
        provider: LLMProvider,
        name: str = "default",
        middleware_timeout: Optional[float] = None,
        provider_timeout: Optional[float] = None,
        max_retries: int = 0,
        retry_base_delay: float = 0.5,
        fallback_providers: Optional[List[LLMProvider]] = None,
        retry_policy: Optional[RetryPolicy] = None,
        enable_circuit_breaker: bool = True,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
        max_stream_chunks: int = 10000,
    ) -> None: ...

    # Middleware management
    def add_middleware(self, middleware: BaseMiddleware) -> "Pipeline": ...
    async def add_middleware_async(self, middleware: BaseMiddleware) -> "Pipeline": ...

    @property
    def middlewares(self) -> List[BaseMiddleware]: ...

    @property
    def provider(self) -> LLMProvider: ...

    # Lifecycle
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def __aenter__(self) -> "Pipeline": ...
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...

    # Call entries
    async def run(self, context: AgentContext) -> LLMResponse: ...
    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]: ...

    # Tool helpers
    async def execute_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall: ...
    async def execute_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult: ...

    # Factory
    @classmethod
    def from_config(
        cls, provider: LLMProvider, config: OnionConfig, name: str = "default"
    ) -> "Pipeline": ...

    # Health check
    def health_check(self) -> Dict[str, Any]:
        """Returns pipeline health status.
        
        Returns:
            {
                "status": "healthy" | "not_started" | "degraded",
                "name": str,
                "started": bool,
                "middlewares_count": int,
                "provider": str,
                "fallback_providers": List[str],
                "circuit_breakers": Dict[str, str],
            }
        """
        ...

    def health_check_sync(self) -> Dict[str, Any]:
        """Synchronous version of health_check()."""
        ...

    # 健康检查
    def health_check(self) -> Dict[str, Any]:
        """返回 Pipeline 的健康状态。
        
        返回值：
            {
                "status": "healthy"（健康）| "not_started"（未启动）| "degraded"（降级）,
                "name": str,                    # Pipeline 名称
                "started": bool,                # 是否已启动
                "middlewares_count": int,       # 中间件数量
                "provider": str,                # 主 Provider 类型
                "fallback_providers": List[str],# Fallback Provider 列表
                "circuit_breakers": Dict[str, str],  # 每个 Provider 的熔断器状态
            }
        
        用法：
            health = pipeline.health_check()
            if health["status"] != "healthy":
                logger.warning("Pipeline 降级: %s", health)
        """
        ...

    def health_check_sync(self) -> Dict[str, Any]:
        """health_check() 的同步版本。"""
        ...
```

**Execution Order Diagram:**
```
Request:  middleware.priority ASC (low → high)
Response: middleware.priority DESC (high → low)
```

**执行顺序图：**
```
请求阶段：中间件按优先级升序执行（低 → 高）
响应阶段：中间件按优先级降序执行（高 → 低）
```

---

## Module: `onion_core.provider`

### `LLMProvider` (Abstract)
```python
class LLMProvider(ABC):
    @property
    def name(self) -> str: ...

    @abstractmethod
    async def complete(self, context: AgentContext) -> LLMResponse: ...

    @abstractmethod
    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]: ...
```

### `EchoProvider`
```python
class EchoProvider(LLMProvider):
    def __init__(self, reply: str = "Hello, I am an agent.") -> None: ...

    async def complete(self, context: AgentContext) -> LLMResponse: ...
    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]: ...
```

---

## Module: `onion_core.providers`

### `OpenAIProvider`
```python
class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        default_headers: Optional[dict] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
        client: Optional[AsyncOpenAI] = None,
    ) -> None: ...
# Pass `client` to share an existing AsyncOpenAI instance (connection pool) across providers.
```

### `AnthropicProvider`
```python
class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
        temperature: float = 1.0,
        base_url: Optional[str] = None,
        client: Optional[AsyncAnthropic] = None,
    ) -> None: ...
# Pass `client` to share an existing AsyncAnthropic instance across providers.
```

### `DeepSeekProvider` (extends `OpenAIProvider`)
```python
class DeepSeekProvider(OpenAIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
    ) -> None: ...
# Base URL: https://api.deepseek.com
```

### `ZhipuAIProvider` (extends `OpenAIProvider`)
```python
# Base URL: https://open.bigmodel.cn/api/paas/v4/
# Default model: glm-4
```

### `MoonshotProvider` (extends `OpenAIProvider`)
```python
# Base URL: https://api.moonshot.cn/v1
# Default model: moonshot-v1-8k
```

### `DashScopeProvider` (extends `OpenAIProvider`)
```python
# Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
# Default model: qwen-turbo
```

### `LocalProvider` (extends `OpenAIProvider`)
```python
class LocalProvider(OpenAIProvider):
    def __init__(
        self,
        base_url: str,            # Required
        api_key: str = "not-needed",
        model: str = "default",
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
    ) -> None: ...
```

### `OllamaProvider` (extends `OpenAIProvider`)
```python
class OllamaProvider(LocalProvider):
    def __init__(
        self,
        model: str,               # Required
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        **kwargs,
    ) -> None: ...
```

### `LMStudioProvider` (extends `OpenAIProvider`)
```python
class LMStudioProvider(LocalProvider):
    def __init__(
        self,
        model: str = "default",
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "lm-studio",
        **kwargs,
    ) -> None: ...
```

---

## Module: `onion_core.middlewares`

### `ObservabilityMiddleware` (priority=100)
```python
class ObservabilityMiddleware(BaseMiddleware):
    priority = 100
    # Sets trace_id in ContextVar, records start time, logs request/response
```

### `SafetyGuardrailMiddleware` (priority=200, mandatory)
```python
class SafetyGuardrailMiddleware(BaseMiddleware):
    priority = 200
    is_mandatory = True

    def __init__(
        self,
        blocked_keywords: Optional[List[str]] = None,
        blocked_tools: Optional[List[str]] = None,
        pii_rules: Optional[List[PiiRule]] = None,
        enable_builtin_pii: bool = True,
        enable_input_pii_masking: bool = False,
    ) -> None: ...

    # PII rules
    add_pii_rule(self, rule: PiiRule) -> "SafetyGuardrailMiddleware": ...
    add_blocked_keyword(self, keyword: str) -> "SafetyGuardrailMiddleware": ...
    add_blocked_tool(self, tool_name: str) -> "SafetyGuardrailMiddleware": ...
```

### `ContextWindowMiddleware` (priority=300)
```python
class ContextWindowMiddleware(BaseMiddleware):
    priority = 300

    def __init__(
        self,
        max_tokens: int = 4000,
        keep_rounds: int = 2,
        encoding_name: str = "cl100k_base",
    ) -> None: ...

    def count_tokens(
        self, messages: List[Message], encoding: Optional = None
    ) -> int: ...
```

### `RateLimitMiddleware` (priority=150, mandatory)
```python
class RateLimitMiddleware(BaseMiddleware):
    priority = 150
    is_mandatory = True

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: float = 60.0,
        max_sessions: int = 10_000,
    ) -> None: ...

    def get_usage(self, session_id: str) -> dict: ...
```

### `MetricsMiddleware` (priority=90)
```python
class MetricsMiddleware(BaseMiddleware):
    priority = 90

    def __init__(self, pipeline_name: str = "default") -> None: ...
```

### `TracingMiddleware` (priority=50)
```python
class TracingMiddleware(BaseMiddleware):
    priority = 50

    def __init__(
        self,
        service_name: str = "onion-core",
        pipeline_name: str = "default",
    ) -> None: ...
```

### `auto_configure_tracing`
```python
def auto_configure_tracing(
    service_name: str = "onion-core",
    otlp_endpoint: Optional[str] = None,
) -> bool: ...
```
Auto-configures OpenTelemetry from environment variables:
`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_TRACES_SAMPLER`.
Returns `True` if tracing was configured, `False` if optional deps are missing.
Requires: `pip install opentelemetry-exporter-otlp`

### `ResponseCacheMiddleware` (priority=75) **[NEW in v0.7.0]**
```python
class ResponseCacheMiddleware(BaseMiddleware):
    """Response caching middleware with TTL and LRU eviction."""
    priority = 75

    def __init__(
        self,
        ttl_seconds: float = 300.0,      # Cache lifetime in seconds
        max_size: int = 1000,             # Maximum cache entries
        cache_key_strategy: str = "full", # "full" | "user_only" | "custom"
    ) -> None: ...

    @property
    def hits(self) -> int:
        """Number of cache hits."""

    @property
    def misses(self) -> int:
        """Number of cache misses."""

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 - 1.0)."""

    def clear_cache(self) -> None:
        """Clear all cached entries."""

    def get_cache_size(self) -> int:
        """Get current number of cached entries."""
```

**Usage Example:**
```python
from onion_core.middlewares import ResponseCacheMiddleware

# Basic usage
cache = ResponseCacheMiddleware(ttl_seconds=600, max_size=500)
pipeline.add_middleware(cache)

# Monitor performance
print(f"Hit rate: {cache.hit_rate:.1%}")
print(f"Cache size: {cache.get_cache_size()}")

# Clear cache if needed
cache.clear_cache()
```

---

## Module: `onion_core.tools`

### `ToolRegistry`
```python
class ToolRegistry:
    def __init__(self) -> None: ...

    # Registration
    def register(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Callable: ...  # Supports @decorator

    def register_func(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> "ToolRegistry": ...  # Fluent interface

    # Query
    def get(self, name: str) -> Optional[ToolDefinition]: ...

    @property
    def tool_names(self) -> List[str]: ...

    # Schema export
    def to_openai_tools(self) -> List[Dict[str, Any]]: ...
    def to_anthropic_tools(self) -> List[Dict[str, Any]]: ...

    # Execution
    def execute(
        self,
        tool_call: ToolCall,
        context: Optional[AgentContext] = None,
    ) -> ToolResult: ...
```

---

## Module: `onion_core.agent`

### `AgentLoop`
```python
class AgentLoop:
    def __init__(
        self,
        pipeline: Pipeline,
        registry: Optional[ToolRegistry] = None,
        max_turns: int = 10,
        raise_on_max_turns: bool = False,
        memory: Optional[SlidingWindowMemory] = None,
    ) -> None: ...

    async def run(self, context: AgentContext) -> LLMResponse: ...

Provides a simplified tool-calling loop on top of a Pipeline.
When `memory` is set, the message list is trimmed by token count
at the start of each turn to prevent unbounded memory growth.

### `AgentRuntime`
```python
class AgentRuntime:
    def __init__(
        self,
        config: AgentConfig,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        planner: Optional[BasePlanner] = None,
        memory: Optional[SlidingWindowMemory] = None,
    ) -> None: ...

    @property
    def state(self) -> AgentState: ...
    @property
    def fsm(self) -> StateMachine: ...
    @property
    def is_idle(self) -> bool: ...

    def on_step(self, callback: Callable[[StepRecord], None]) -> None: ...
    def on_error(self, callback: Callable[[str, Exception], None]) -> None: ...
    def cancel(self) -> None: ...
    async def drain(self, timeout: float = 30.0) -> None: ...

    async def run(self, user_message: str, state: Optional[AgentState] = None) -> AgentState: ...
    async def run_streaming(self, user_message: str, state: Optional[AgentState] = None) -> AsyncIterator[StepRecord]: ...
    async def run_streaming_text(self, user_message: str, state: Optional[AgentState] = None) -> AsyncIterator[StreamChunk]: ...

Full ReAct agent with state machine, planner, memory management,
and tool execution. `run_streaming_text()` yields StreamChunk tokens
in real time for typewriter-style output.
```

### `install_signal_handlers`
```python
def install_signal_handlers(agent: Optional[AgentRuntime] = None, timeout: float = 30.0) -> None: ...
```
Registers SIGTERM/SIGINT handlers for graceful shutdown.
Calls `agent.cancel()` and `agent.drain()` on first signal;
forces `SystemExit(1)` on second signal.

### `shutdown_requested`
```python
def shutdown_requested() -> bool: ...
```
Returns `True` if a termination signal has been received.

---

## Module: `onion_core.config`

### Configuration Classes
```python
class SafetyConfig(BaseModel):
    blocked_keywords: List[str] = Field(default_factory=list)
    blocked_tools: List[str] = Field(default_factory=list)
    enable_pii_masking: bool = True

class ContextWindowConfig(BaseModel):
    max_tokens: int = 4000
    keep_rounds: int = 2
    encoding_name: str = "cl100k_base"

class ObservabilityConfig(BaseModel):
    log_level: str = "INFO"
    log_tool_args: bool = True

class PipelineConfig(BaseModel):
    middleware_timeout: Optional[float] = None
    provider_timeout: Optional[float] = None
    max_retries: int = 0
    enable_circuit_breaker: bool = True
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 30.0
    max_stream_chunks: int = 10000

class OnionConfig(BaseSettings):
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    context_window: ContextWindowConfig = Field(default_factory=ContextWindowConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "OnionConfig": ...

    @classmethod
    def from_env(cls) -> "OnionConfig": ...

    def get(self, key: str, default=None) -> Any: ...
    def to_context_config(self) -> Dict[str, Any]: ...
```

**Environment Variable Prefix:** `ONION__`

Example: `ONION__PIPELINE__MAX_RETRIES=3`

---

## Module: `onion_core.error_codes`

### Factory Functions
```python
def security_error(
    code: ErrorCode = ErrorCode.SECURITY_BLOCKED_KEYWORD,
    message: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> OnionErrorWithCode: ...

def provider_error(
    code: ErrorCode = ErrorCode.PROVIDER_INVALID_REQUEST,
    message: Optional[str] = None,
    cause: Optional[Exception] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> OnionErrorWithCode: ...

def fallback_error(
    code: ErrorCode = ErrorCode.FALLBACK_EXHAUSTED,
    message: Optional[str] = None,
    cause: Optional[Exception] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> OnionErrorWithCode: ...
```

### Mappings
```python
ERROR_MESSAGES: Dict[ErrorCode, str]       # Default human-readable messages
ERROR_RETRY_POLICY() -> Dict[ErrorCode, RetryOutcome]  # Lazy-loaded retry policy
```

---

## Module: `onion_core.models` (Token Limits)

### `ModelTokenLimits`
```python
class ModelTokenLimits(BaseModel):
    max_context: int       # Max total context window
    max_output: int        # Max output tokens
    encoding: str          # tiktoken encoding name
```

### `MODEL_TOKEN_LIMITS`
```python
MODEL_TOKEN_LIMITS: Dict[str, ModelTokenLimits] = {
    "gpt-4o":   ModelTokenLimits(max_context=128000, max_output=16384, ...),
    "claude-3-5-sonnet-20241022": ModelTokenLimits(max_context=200000, ...),
    "deepseek-chat": ModelTokenLimits(max_context=64000, ...),
    # See source for the full list
}
```

### `lookup_model_limits`
```python
def lookup_model_limits(model: str) -> Optional[ModelTokenLimits]: ...
```
Prefix-matches a model name against `MODEL_TOKEN_LIMITS`.
Used by `AgentRuntime._auto_tune_config()` to set sensible defaults.

---

# Onion Core - API 参考

> 版本：0.8.0 | 更新日期：2026-04-26

本文档描述 `onion_core` 包中的所有公共类、函数和配置选项。

---

## 包导出 (`onion_core.__init__`)

```python
from onion_core import (
    # 核心
    Pipeline, MiddlewareManager, BaseMiddleware,
    # Provider
    LLMProvider, EchoProvider,
    # 模型
    AgentContext, Message, MessageRole,
    LLMResponse, StreamChunk, ToolCall, ToolResult,
    UsageStats, MiddlewareEvent, FinishReason,
    # 错误与重试
    OnionError, SecurityException, RateLimitExceeded,
    ProviderError, RetryPolicy, RetryOutcome,
    # 错误码（新增）
    ErrorCode, OnionErrorWithCode,
    ERROR_MESSAGES, ERROR_RETRY_POLICY,
    security_error, provider_error, fallback_error,
    # 配置
    OnionConfig, PipelineConfig, SafetyConfig,
    ContextWindowConfig, ObservabilityConfig,
    # Agent
    AgentLoop, AgentLoopError,
    # 版本
    __version__,
)
```

---

## 模块：`onion_core.models`

### 枚举

#### `MessageRole`
```python
MessageRole = Literal["system", "user", "assistant", "tool"]
```

#### `FinishReason`
```python
class FinishReason(str, Enum):
    STOP = "stop"              # 正常完成
    LENGTH = "length"          # 因 max tokens 截断
    TOOL_CALLS = "tool_calls"  # 模型请求工具调用
    CONTENT_FILTER = "content_filter"  # 被内容过滤器阻止
    ERROR = "error"            # 发生错误
```

#### `CircuitState`
```python
class CircuitState(str, Enum):
    CLOSED = "closed"          # 正常：请求通过
    OPEN = "open"              # 熔断：请求被拒绝
    HALF_OPEN = "half_open"    # 半开：允许有限请求
```

#### `RetryOutcome`
```python
class RetryOutcome(str, Enum):
    RETRY = "retry"             # 瞬时故障：指数退避
    FALLBACK = "fallback"       # 服务错误：尝试下一个 provider
    FATAL = "fatal"             # 致命错误：立即抛出
```

#### `MiddlewareEvent`
```python
class MiddlewareEvent(str, Enum):
    ON_REQUEST = "on_request"
    ON_RESPONSE = "on_response"
    ON_STREAM_CHUNK = "on_stream_chunk"
    ON_ERROR = "on_error"
    ON_TOOL_CALL = "on_tool_call"
    ON_TOOL_RESULT = "on_tool_result"
```

#### `ErrorCode`
```python
class ErrorCode(str, Enum):
    # Security (100-199)
    SECURITY_BLOCKED_KEYWORD   = "ONI-S100"
    SECURITY_PII_DETECTED      = "ONI-S101"
    SECURITY_PROMPT_INJECTION  = "ONI-S102"
    SECURITY_FORBIDDEN_TOOL    = "ONI-S103"
    # Rate Limit (200-299)
    RATE_LIMIT_EXCEEDED        = "ONI-R200"
    RATE_LIMIT_WINDOW_FULL     = "ONI-R201"
    # Circuit Breaker (300-399)
    CIRCUIT_OPEN               = "ONI-C300"
    CIRCUIT_TRIPPED            = "ONI-C301"
    # Provider (400-499)
    PROVIDER_AUTH_FAILED       = "ONI-P400"
    PROVIDER_QUOTA_EXCEEDED   = "ONI-P401"
    PROVIDER_MODEL_NOT_FOUND  = "ONI-P402"
    PROVIDER_CONTENT_FILTER   = "ONI-P403"
    PROVIDER_CONTEXT_OVERFLOW = "ONI-P404"
    PROVIDER_INVALID_REQUEST  = "ONI-P405"
    # Middleware (500-599)
    MIDDLEWARE_REQUEST_FAILED  = "ONI-M500"
    MIDDLEWARE_RESPONSE_FAILED = "ONI-M501"
    MIDDLEWARE_STREAM_FAILED   = "ONI-M502"
    MIDDLEWARE_TIMEOUT         = "ONI-M503"
    MIDDLEWARE_CHAIN_ABORTED  = "ONI-M504"
    # Validation (600-699)
    VALIDATION_INVALID_CONFIG  = "ONI-V600"
    VALIDATION_INVALID_MESSAGE = "ONI-V601"
    VALIDATION_INVALID_TOOL_CALL = "ONI-V602"
    VALIDATION_INVALID_CONTEXT = "ONI-V603"
    # Timeout (700-799)
    TIMEOUT_PROVIDER           = "ONI-T700"
    TIMEOUT_MIDDLEWARE         = "ONI-T701"
    TIMEOUT_TOTAL_PIPELINE    = "ONI-T702"
    # Fallback (800-899)
    FALLBACK_TRIGGERED        = "ONI-F800"
    FALLBACK_EXHAUSTED        = "ONI-F801"
    FALLBACK_PROVIDER_FAILED  = "ONI-F802"
    # Internal (900-999)
    INTERNAL_UNEXPECTED       = "ONI-I900"
    INTERNAL_NOT_IMPLEMENTED  = "ONI-I901"
    INTERNAL_STATE_CORRUPT    = "ONI-I902"
```

---

### 数据模型 (Pydantic)

#### `Message`
```python
class Message(BaseModel):
    role: MessageRole
    content: Union[str, List[ContentBlock]]
    name: Optional[str] = None

    @property
    def text_content(self) -> str: ...
```

#### `AgentContext`
```python
class AgentContext(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    messages: List[Message] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
```

#### `ToolCall`
```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
```

#### `ToolResult`
```python
class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    result: Optional[Union[str, Dict[str, Any], List[Any]]] = None
    error: Optional[str] = None

    @property
    def is_error(self) -> bool: ...
```

#### `UsageStats`
```python
class UsageStats(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

#### `LLMResponse`
```python
class LLMResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    finish_reason: Optional[FinishReason] = None
    usage: Optional[UsageStats] = None
    model: Optional[str] = None
    raw: Optional[Any] = None

    @property
    def has_tool_calls(self) -> bool: ...

    @property
    def is_complete(self) -> bool: ...
```

#### `StreamChunk`
```python
class StreamChunk(BaseModel):
    delta: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    finish_reason: Optional[FinishReason] = None
    index: int = 0
```

---

### 异常类

#### `OnionError`
```python
class OnionError(Exception):
    """所有 Onion Core 错误的基类。"""
```

#### `SecurityException(OnionError)`
```python
class SecurityException(OnionError):
    is_fatal: bool = True
```

#### `RateLimitExceeded(OnionError)`
```python
class RateLimitExceeded(OnionError):
    is_fatal: bool = True
```

#### `ProviderError(OnionError)`
```python
class ProviderError(OnionError):
    is_fatal: bool = False
```

#### `CircuitBreakerError(OnionError)`
```python
class CircuitBreakerError(OnionError):
    is_fatal: bool = False
```

#### `OnionErrorWithCode(Exception)` (新增)
```python
class OnionErrorWithCode(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: Optional[str] = None,
        cause: Optional[Exception] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    @property
    def retry_outcome(self) -> RetryOutcome: ...

    @property
    def is_fatal(self) -> bool: ...

    def to_dict(self) -> Dict[str, Any]: ...
```

#### Retry Policy
```python
class RetryPolicy:
    def classify(self, exc: Exception) -> RetryOutcome: ...
    def is_retryable(self, exc: Exception) -> bool: ...
    def is_fatal(self, exc: Exception) -> bool: ...
    def is_chain_breaking(self, exc: Exception) -> bool: ...
```

---

## 模块：`onion_core.base`

### `BaseMiddleware`
```python
class BaseMiddleware(ABC):
    priority: int = 500
    timeout: Optional[float] = None
    is_mandatory: bool = False

    @property
    def name(self) -> str: ...

    # 生命周期
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...

    # 必须实现（抽象）
    async def process_request(self, context: AgentContext) -> AgentContext: ...
    async def process_response(
        self, context: AgentContext, response: LLMResponse
    ) -> LLMResponse: ...

    # 可选（默认：透传）
    async def process_stream_chunk(
        self, context: AgentContext, chunk: StreamChunk
    ) -> StreamChunk: ...

    async def on_tool_call(
        self, context: AgentContext, tool_call: ToolCall
    ) -> ToolCall: ...

    async def on_tool_result(
        self, context: AgentContext, result: ToolResult
    ) -> ToolResult: ...

    async def on_error(
        self, context: AgentContext, error: Exception
    ) -> None: ...
```

---

## 模块：`onion_core.pipeline`

### `Pipeline`
```python
class Pipeline:
    def __init__(
        self,
        provider: LLMProvider,
        name: str = "default",
        middleware_timeout: Optional[float] = None,
        provider_timeout: Optional[float] = None,
        max_retries: int = 0,
        retry_base_delay: float = 0.5,
        fallback_providers: Optional[List[LLMProvider]] = None,
        retry_policy: Optional[RetryPolicy] = None,
        enable_circuit_breaker: bool = True,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
        max_stream_chunks: int = 10000,
    ) -> None: ...

    # 中间件管理
    def add_middleware(self, middleware: BaseMiddleware) -> "Pipeline": ...
    async def add_middleware_async(self, middleware: BaseMiddleware) -> "Pipeline": ...

    @property
    def middlewares(self) -> List[BaseMiddleware]: ...

    @property
    def provider(self) -> LLMProvider: ...

    # 生命周期
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def __aenter__(self) -> "Pipeline": ...
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...

    # 调用入口
    async def run(self, context: AgentContext) -> LLMResponse: ...
    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]: ...

    # 工具辅助方法
    async def execute_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall: ...
    async def execute_tool_result(self, context: AgentContext, result: ToolResult) -> ToolResult: ...

    # 工厂方法
    @classmethod
    def from_config(
        cls, provider: LLMProvider, config: OnionConfig, name: str = "default"
    ) -> "Pipeline": ...
```

**执行顺序图：**
```
请求阶段:  middleware.priority ASC (低 → 高)
响应阶段:  middleware.priority DESC (高 → 低)
```

---

## 模块：`onion_core.provider`

### `LLMProvider` (抽象)
```python
class LLMProvider(ABC):
    @property
    def name(self) -> str: ...

    @abstractmethod
    async def complete(self, context: AgentContext) -> LLMResponse: ...

    @abstractmethod
    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]: ...
```

### `EchoProvider`
```python
class EchoProvider(LLMProvider):
    def __init__(self, reply: str = "Hello, I am an agent.") -> None: ...

    async def complete(self, context: AgentContext) -> LLMResponse: ...
    async def stream(self, context: AgentContext) -> AsyncIterator[StreamChunk]: ...
```

---

## 模块：`onion_core.providers`

### `OpenAIProvider`
```python
class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        default_headers: Optional[dict] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
        client: Optional[AsyncOpenAI] = None,
    ) -> None: ...
# 传入 `client` 可共享已有的 AsyncOpenAI 实例（连接池），避免重复创建。
```

### `AnthropicProvider`
```python
class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
        temperature: float = 1.0,
        base_url: Optional[str] = None,
        client: Optional[AsyncAnthropic] = None,
    ) -> None: ...
# 传入 `client` 可共享已有的 AsyncAnthropic 实例，避免重复创建连接池。
```

### `DeepSeekProvider` (继承自 `OpenAIProvider`)
```python
class DeepSeekProvider(OpenAIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
    ) -> None: ...
# Base URL: https://api.deepseek.com
```

### `ZhipuAIProvider` (继承自 `OpenAIProvider`)
```python
# Base URL: https://open.bigmodel.cn/api/paas/v4/
# 默认模型: glm-4
```

### `MoonshotProvider` (继承自 `OpenAIProvider`)
```python
# Base URL: https://api.moonshot.cn/v1
# 默认模型: moonshot-v1-8k
```

### `DashScopeProvider` (继承自 `OpenAIProvider`)
```python
# Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
# 默认模型: qwen-turbo
```

### `LocalProvider` (继承自 `OpenAIProvider`)
```python
class LocalProvider(OpenAIProvider):
    def __init__(
        self,
        base_url: str,            # 必需
        api_key: str = "not-needed",
        model: str = "default",
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
    ) -> None: ...
```

### `OllamaProvider` (继承自 `OpenAIProvider`)
```python
class OllamaProvider(LocalProvider):
    def __init__(
        self,
        model: str,               # 必需
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        **kwargs,
    ) -> None: ...
```

### `LMStudioProvider` (继承自 `OpenAIProvider`)
```python
class LMStudioProvider(LocalProvider):
    def __init__(
        self,
        model: str = "default",
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "lm-studio",
        **kwargs,
    ) -> None: ...
```

---

## 模块：`onion_core.middlewares`

### `ObservabilityMiddleware` (priority=100)
```python
class ObservabilityMiddleware(BaseMiddleware):
    priority = 100
    # 在 ContextVar 中设置 trace_id，记录起始时间，记录请求/响应日志
```

### `SafetyGuardrailMiddleware` (priority=200, mandatory)
```python
class SafetyGuardrailMiddleware(BaseMiddleware):
    priority = 200
    is_mandatory = True

    def __init__(
        self,
        blocked_keywords: Optional[List[str]] = None,
        blocked_tools: Optional[List[str]] = None,
        pii_rules: Optional[List[PiiRule]] = None,
        enable_builtin_pii: bool = True,
        enable_input_pii_masking: bool = False,
    ) -> None: ...

    # PII 规则
    add_pii_rule(self, rule: PiiRule) -> "SafetyGuardrailMiddleware": ...
    add_blocked_keyword(self, keyword: str) -> "SafetyGuardrailMiddleware": ...
    add_blocked_tool(self, tool_name: str) -> "SafetyGuardrailMiddleware": ...
```

### `ContextWindowMiddleware` (priority=300)
```python
class ContextWindowMiddleware(BaseMiddleware):
    priority = 300

    def __init__(
        self,
        max_tokens: int = 4000,
        keep_rounds: int = 2,
        encoding_name: str = "cl100k_base",
    ) -> None: ...

    def count_tokens(
        self, messages: List[Message], encoding: Optional = None
    ) -> int: ...
```

### `RateLimitMiddleware` (priority=150, mandatory)
```python
class RateLimitMiddleware(BaseMiddleware):
    priority = 150
    is_mandatory = True

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: float = 60.0,
        max_sessions: int = 10_000,
    ) -> None: ...

    def get_usage(self, session_id: str) -> dict: ...
```

### `MetricsMiddleware` (priority=90)
```python
class MetricsMiddleware(BaseMiddleware):
    priority = 90

    def __init__(self, pipeline_name: str = "default") -> None: ...
```

### `TracingMiddleware` (priority=50)
```python
class TracingMiddleware(BaseMiddleware):
    priority = 50

    def __init__(
        self,
        service_name: str = "onion-core",
        pipeline_name: str = "default",
    ) -> None: ...
```

### `auto_configure_tracing`
```python
def auto_configure_tracing(
    service_name: str = "onion-core",
    otlp_endpoint: Optional[str] = None,
) -> bool: ...
```
从环境变量自动配置 OpenTelemetry 追踪导出。
读取 `OTEL_EXPORTER_OTLP_ENDPOINT`、`OTEL_SERVICE_NAME` 等变量。
可选依赖：`pip install opentelemetry-exporter-otlp`

---

## 模块：`onion_core.tools`

### `ToolRegistry`
```python
class ToolRegistry:
    def __init__(self) -> None: ...

    # 注册
    def register(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Callable: ...  # 支持 @装饰器

    def register_func(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> "ToolRegistry": ...  # 链式接口

    # 查询
    def get(self, name: str) -> Optional[ToolDefinition]: ...

    @property
    def tool_names(self) -> List[str]: ...

    # Schema 导出
    def to_openai_tools(self) -> List[Dict[str, Any]]: ...
    def to_anthropic_tools(self) -> List[Dict[str, Any]]: ...

    # 执行
    async def execute(
        self,
        tool_call: ToolCall,
        context: Optional[AgentContext] = None,
    ) -> ToolResult: ...
```

---

## 模块：`onion_core.agent`

### `AgentLoop`
```python
class AgentLoop:
    def __init__(
        self,
        pipeline: Pipeline,
        registry: Optional[ToolRegistry] = None,
        max_turns: int = 10,
        raise_on_max_turns: bool = False,
        memory: Optional[SlidingWindowMemory] = None,
    ) -> None: ...

    async def run(self, context: AgentContext) -> LLMResponse: ...

在 Pipeline 之上提供简化的工具调用循环。
当传入 `memory` 参数时，每轮循环开始时按 token 数裁剪消息列表，
防止长时间运行的 Agent 出现内存泄漏。

### `AgentRuntime`
```python
class AgentRuntime:
    def __init__(
        self,
        config: AgentConfig,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        planner: Optional[BasePlanner] = None,
        memory: Optional[SlidingWindowMemory] = None,
    ) -> None: ...

    @property
    def state(self) -> AgentState: ...
    @property
    def fsm(self) -> StateMachine: ...
    @property
    def is_idle(self) -> bool: ...

    def on_step(self, callback: Callable[[StepRecord], None]) -> None: ...
    def on_error(self, callback: Callable[[str, Exception], None]) -> None: ...
    def cancel(self) -> None: ...
    async def drain(self, timeout: float = 30.0) -> None: ...

    async def run(self, user_message: str, state: Optional[AgentState] = None) -> AgentState: ...
    async def run_streaming(self, user_message: str, state: Optional[AgentState] = None) -> AsyncIterator[StepRecord]: ...
    async def run_streaming_text(self, user_message: str, state: Optional[AgentState] = None) -> AsyncIterator[StreamChunk]: ...

完整的 ReAct Agent，包含状态机、规划器、记忆管理和工具执行。
`run_streaming_text()` 实时流式输出 token 级别的 StreamChunk。
```

### `install_signal_handlers`
```python
def install_signal_handlers(agent: Optional[AgentRuntime] = None, timeout: float = 30.0) -> None: ...
```
注册 SIGTERM/SIGINT 信号处理函数，实现优雅关闭。
首次信号触发 `agent.cancel()` + `agent.drain()`，重复信号强制退出。

### `shutdown_requested`
```python
def shutdown_requested() -> bool: ...
```
返回是否已收到终止信号。

---

## 模块：`onion_core.config`

### 配置类
```python
class SafetyConfig(BaseModel):
    blocked_keywords: List[str] = Field(default_factory=list)
    blocked_tools: List[str] = Field(default_factory=list)
    enable_pii_masking: bool = True

class ContextWindowConfig(BaseModel):
    max_tokens: int = 4000
    keep_rounds: int = 2
    encoding_name: str = "cl100k_base"

class ObservabilityConfig(BaseModel):
    log_level: str = "INFO"
    log_tool_args: bool = True

class PipelineConfig(BaseModel):
    middleware_timeout: Optional[float] = None
    provider_timeout: Optional[float] = None
    max_retries: int = 0
    enable_circuit_breaker: bool = True
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 30.0
    max_stream_chunks: int = 10000

class OnionConfig(BaseSettings):
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    context_window: ContextWindowConfig = Field(default_factory=ContextWindowConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "OnionConfig": ...

    @classmethod
    def from_env(cls) -> "OnionConfig": ...

    def get(self, key: str, default=None) -> Any: ...
    def to_context_config(self) -> Dict[str, Any]: ...
```

**环境变量前缀：** `ONION__`

示例：`ONION__PIPELINE__MAX_RETRIES=3`

---

## 模块：`onion_core.error_codes`

### 工厂函数
```python
def security_error(
    code: ErrorCode = ErrorCode.SECURITY_BLOCKED_KEYWORD,
    message: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> OnionErrorWithCode: ...

def provider_error(
    code: ErrorCode = ErrorCode.PROVIDER_INVALID_REQUEST,
    message: Optional[str] = None,
    cause: Optional[Exception] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> OnionErrorWithCode: ...

def fallback_error(
    code: ErrorCode = ErrorCode.FALLBACK_EXHAUSTED,
    message: Optional[str] = None,
    cause: Optional[Exception] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> OnionErrorWithCode: ...
```

### 映射表
```python
ERROR_MESSAGES: Dict[ErrorCode, str]       # 默认人类可读消息
ERROR_RETRY_POLICY() -> Dict[ErrorCode, RetryOutcome]  # 延迟加载的重试策略
```
