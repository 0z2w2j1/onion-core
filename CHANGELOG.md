# Changelog

## [Unreleased]

### Added

- New unified error code system (`onion_core/error_codes.py`)
  - Defines `ErrorCode` enum covering Security / RateLimit / CircuitBreaker / Provider / Middleware / Validation / Timeout / Fallback / Internal nine major error categories
  - New `OnionErrorWithCode` exception base class supporting error codes, cause chain, and extra fields
  - New `ERROR_MESSAGES` / `ERROR_RETRY_POLICY` mapping tables
  - New `security_error()` / `provider_error()` / `fallback_error()` convenience factory functions
- New degradation strategy document (`docs/degradation_strategy.md`)
  - Error classification and handling strategy (RETRY / FALLBACK / FATAL)
  - Exponential backoff retry algorithm
  - Circuit breaker state machine and parameter configuration
  - Fallback Provider chain execution order
  - Middleware fault isolation mechanism
  - Production environment configuration suggestions and monitoring alert metrics
- New error code usage guide (`docs/error_code_usage.md`)
  - Quick start examples (new way / factory function / backward compatibility)
  - Usage examples in middleware and Provider
  - Error serialization, structured logging, HTTP API response examples
  - Custom error code extension method
  - Complete error code reference table
- Ruff linter integration for code quality
- Updated documentation dates to 2026-04-24
- `pyproject.toml` new `Documentation` URL
- `README.md` updated with new features and badges

### Changed

- `onion_core/__init__.py` new exports `ErrorCode`, `OnionErrorWithCode`, `ERROR_MESSAGES`, `ERROR_RETRY_POLICY`, etc.
- `onion_core/models.py` fixed `CircuitState` class definition location
- Updated Python version requirement to 3.11+ (from 3.9+)
- Enhanced Pipeline with improved circuit breaker and fallback provider coordination
- Improved middleware fault isolation with better error handling

### Fixed

- Fixed circular import issue between `models.py` and `error_codes.py` (resolved via `TYPE_CHECKING` + lazy import)
- Restored deleted `CircuitState` enum definition in `models.py`
- Documentation date consistency across all files

---

## [0.5.0] - 2026-04-23

### Added

- Initial release
- Middleware framework (BaseMiddleware + Pipeline)
- LLM Provider abstraction (OpenAI / Anthropic / Domestic AI / Local AI)
- Security guardrail (PII masking, prompt injection detection)
- Context window management (tiktoken counting, intelligent truncation)
- Rate limiting & circuit breaker (sliding window, Circuit Breaker state machine)
- Observability (structured logging, Prometheus Metrics, OpenTelemetry Tracing)
- Agent Loop (multi-turn tool call orchestration)
- Tool Registry (decorator registration, automatic JSON Schema generation)
- Configuration system (code / environment variables / JSON+YAML files)
- Test suite (110 test cases, pytest + pytest-asyncio)

---

# 变更日志

## [未发布]

### 新增

- 新增统一错误码系统 (`onion_core/error_codes.py`)
  - 定义 `ErrorCode` 枚举，覆盖 Security / RateLimit / CircuitBreaker / Provider / Middleware / Validation / Timeout / Fallback / Internal 九大类错误
  - 新增 `OnionErrorWithCode` 异常基类，支持错误码、cause 链、extra 字段
  - 新增 `ERROR_MESSAGES` / `ERROR_RETRY_POLICY` 映射表
  - 新增 `security_error()` / `provider_error()` / `fallback_error()` 便捷工厂函数
- 新增降级策略文档 (`docs/degradation_strategy.md`)
  - 错误分类与处置策略（RETRY / FALLBACK / FATAL）
  - 指数退避重试算法说明
  - 熔断器状态机与参数配置
  - Fallback Provider 链执行顺序
  - 中间件故障隔离机制
  - 生产环境配置建议与监控告警指标
- 新增错误码使用指南 (`docs/error_code_usage.md`)
  - 快速开始示例（新方式 / 工厂函数 / 向后兼容）
  - 在中间件和 Provider 中的使用示例
  - 错误序列化、结构化日志、HTTP API 响应示例
  - 自定义错误码扩展方法
  - 完整错误码参考表
- 集成 Ruff 代码检查工具
- 更新所有文档日期至 2026-04-24
- `pyproject.toml` 新增 `Documentation` URL
- `README.md` 更新新功能和徽章

### 更改

- `onion_core/__init__.py` 新增导出 `ErrorCode`, `OnionErrorWithCode`, `ERROR_MESSAGES`, `ERROR_RETRY_POLICY` 等
- `onion_core/models.py` 修复 `CircuitState` 类定义位置（此前编辑失误导致结构错误）
- Python 版本要求更新至 3.11+（从 3.9+）
- 增强 Pipeline 的熔断器和 Fallback Provider 协调机制
- 改进中间件故障隔离和错误处理

### 修复

- 修复 `models.py` 与 `error_codes.py` 之间的循环导入问题（通过 `TYPE_CHECKING` + 延迟导入解决）
- 恢复 `models.py` 中被误删的 `CircuitState` 枚举定义
- 修复所有文档日期一致性问题

---

## [0.5.0] - 2026-04-23

### 新增

- 初始版本发布
- 中间件框架（BaseMiddleware + Pipeline）
- LLM Provider 抽象（OpenAI / Anthropic / 国内 AI / 本地 AI）
- 安全护栏（PII 脱敏、提示词注入检测）
- 上下文窗口管理（tiktoken 计数、智能裁剪）
- 限流与熔断（滑动窗口、Circuit Breaker 状态机）
- 可观测性（结构化日志、Prometheus Metrics、OpenTelemetry Tracing）
- Agent Loop（多轮工具调用编排）
- Tool Registry（装饰器注册、自动 JSON Schema 生成）
- 配置系统（代码 / 环境变量 / JSON+YAML 文件）
- 测试套件（110 个测试用例，pytest + pytest-asyncio）
