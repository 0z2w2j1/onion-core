# 🧅 Onion Core

<div align="center">

**Agent Middleware Framework — Onion-Model Pipeline for LLM Applications**

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/0z2w2j1/onion-core)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Test Status](https://github.com/0z2w2j1/onion-core/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/0z2w2j1/onion-core/actions)
[![Coverage](https://codecov.io/gh/0z2w2j1/onion-core/branch/main/graph/badge.svg)](https://codecov.io/gh/0z2w2j1/onion-core)
[![mypy](https://img.shields.io/badge/mypy-strict-blue.svg)]()
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)]()

[English](#english) | [中文](#中文)

</div>

---

## English

### Overview

**Onion Core** is a middleware framework for AI Agent applications. It wraps LLM calls with layered "onion skins" — each layer provides **security, reliability, and observability** capabilities for your Agent.

```
        User Request
             │
             ▼
    ┌─────────────────────────┐
    │ [1] Tracing    (50)     │◄── Outer
    │ [2] Metrics    (90)     │
    │ [3] Observability(100)  │
    │ [4] Rate Limit (150)    │
    │ [5] Safety     (200)    │
    │ [6] Context    (300)    │
    └──────────┬──────────────┘
               │
               ▼
          [ LLM Provider ]
               │
               ▼
    ┌─────────────────────────┐
    │ [6] Context    (300)    │
    │ [5] Safety     (200)    │
    │ [4] Rate Limit (150)    │
    │ [3] Observability(100)   │
    │ [2] Metrics    (90)     │
    │ [1] Tracing    (50)     │◄── Inner
    └──────────┬──────────────┘
               │
               ▼
        Final Response
```

---

### Why Onion Core?

Building a simple chatbot is easy. Building a **production-grade** AI application is hard. Onion Core solves the "heavy lifting":

| Problem | Onion Core Solution |
|---------|---------------------|
| **Security anxiety** — prompt injection, PII leakage | `SafetyGuardrailMiddleware`: keyword blocking, PII masking (email, phone, ID) |
| **Cost control** — token explosion, context overflow | `ContextWindowMiddleware`: tiktoken-based counting, auto-truncation |
| **Service instability** — API timeouts, rate limits | Retry with exponential backoff + Fallback Providers + Circuit Breaker |
| **Black box** — no visibility into what happened | Structured JSON logs, Prometheus metrics, OpenTelemetry tracing |

---

### Quick Start

#### Install

```bash
# Basic install
pip install onion-core

# With OpenAI / Domestic AI (DeepSeek, GLM, Kimi, Qwen)
pip install "onion-core[openai]"

# With Anthropic
pip install "onion-core[anthropic]"

# All-in-one
pip install "onion-core[all]"
```

#### Your First Pipeline

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message, EchoProvider
from onion_core.middlewares import (
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
    ObservabilityMiddleware,
)

async def main():
    async with Pipeline(
        provider=EchoProvider(),
        max_retries=2,
        enable_circuit_breaker=True,
    ) as p:
        p.add_middleware(ObservabilityMiddleware())
        p.add_middleware(SafetyGuardrailMiddleware())
        p.add_middleware(ContextWindowMiddleware(max_tokens=2000))

        ctx = AgentContext(messages=[
            Message(role="user", content="My phone is 13812345678")
        ])
        response = await p.run(ctx)
        print(response.content)
        # Output: Echo: My phone is ***127899999

if __name__ == "__main__":
    asyncio.run(main())
```

#### Synchronous API (for Flask/Django/Scripts)

> **⚠️ Important Limitations:**
> - Sync methods **cannot** be called from within an async context (will raise `RuntimeError`)
> - `stream_sync()` collects all chunks in memory before yielding (bounded by `max_stream_chunks`, default 10,000)
> - For best performance in async applications, always use `await pipeline.run()` and `async for chunk in pipeline.stream()`

```python
from onion_core import Pipeline, AgentContext, Message, EchoProvider
from onion_core.middlewares import (
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
    ObservabilityMiddleware,
)

# Use synchronous context manager
with Pipeline(
    provider=EchoProvider(),
    max_retries=2,
    enable_circuit_breaker=True,
) as p:
    p.add_middleware(ObservabilityMiddleware())
    p.add_middleware(SafetyGuardrailMiddleware())
    p.add_middleware(ContextWindowMiddleware(max_tokens=2000))

    ctx = AgentContext(messages=[
        Message(role="user", content="My phone is 13812345678")
    ])
    response = p.run_sync(ctx)  # Note: run_sync instead of await p.run()
    print(response.content)
    # Output: Echo: My phone is ***127899999

# Streaming also has sync version
with Pipeline(provider=EchoProvider()) as p:
    ctx = AgentContext(messages=[Message(role="user", content="Hello")])
    for chunk in p.stream_sync(ctx):  # Note: stream_sync instead of p.stream()
        if chunk.delta:
            print(chunk.delta, end="", flush=True)
```

---

### Core Features

#### 🛡️ Security Guardrail
- Built-in prompt injection detection
- PII masking: email, China phone, intl phone, ID card, credit card
- **Streaming PII masking with timeout**: Time-based buffer flush (2s max) to ensure low TTFT
- Tool call blocking

#### 🌏 Domestic AI Support
```python
from onion_core.providers.domestic import DeepSeekProvider, ZhipuAIProvider

provider = DeepSeekProvider(api_key="sk-...")   # DeepSeek V3/R1
provider = ZhipuAIProvider(api_key="...")        # GLM-4
```

#### 🏠 Local / Self-hosted AI
```python
from onion_core.providers.local import OllamaProvider, LMStudioProvider

provider = OllamaProvider(model="llama3")                    # localhost:11434
provider = LMStudioProvider()                                  # localhost:1234
provider = LocalProvider(base_url="http://192.168.1.100:8000/v1")  # vLLM, etc.
```

#### 📏 Context Window Management
- Accurate token counting with `tiktoken` (OpenAI-compatible)
- **Async computation**: ThreadPoolExecutor for long messages (>1000 chars) to avoid event loop blocking
- Auto-truncation: preserves system prompt + latest N rounds
- AgentState synchronization: truncated context automatically synced back to agent memory

#### ⚡ Rate Limiting & Circuit Breaker
- **Layered rate limiting**: Separate limits for regular requests vs tool calls (prevents tool call storms)
- Per-session sliding window (in-memory, single-process)
- Circuit breaker: stops hitting a failing provider (CLOSED → OPEN → HALF_OPEN → CLOSED)
- **Note**: Distributed backends (Redis/Etcd) are planned for v1.0

#### 📊 Production Observability
- Structured JSON logging with `request_id`
- Prometheus metrics (`onion_requests_total`, `onion_request_duration_seconds`, etc.)
- OpenTelemetry distributed tracing

#### 🤖 Agent Loop
```python
from onion_core import AgentLoop, ToolRegistry

registry = ToolRegistry()
@registry.register
def get_weather(city: str) -> str:
    return f"Sunny in {city}"

agent = AgentLoop(pipeline=p, registry=registry)
response = await agent.run(context)
```

---

### Configuration

Environment variables (prefix `ONION__`):

```bash
export ONION__PIPELINE__MAX_RETRIES=3
export ONION__CONTEXT_WINDOW__MAX_TOKENS=8000
export ONION__SAFETY__ENABLE_PII_MASKING=true
```

Or from file (`onion.json` / `onion.yaml`):

```json
{
  "pipeline": {"max_retries": 3},
  "safety": {"enable_pii_masking": true}
}
```

---

### Documentation

| Document | Description |
|----------|-------------|
| [API Reference](docs/api_reference.md) | Complete API signatures for all classes and functions |
| [Architecture Design](docs/architecture.md) | System design, data flow, extensibility guide |
| [Error Code Usage](docs/error_code_usage.md) | How to use `ErrorCode` and `OnionErrorWithCode` |
| [Degradation Strategy](docs/degradation_strategy.md) | Retry, circuit breaker, fallback provider chain |
| [Monitoring & Alerting](docs/monitoring_guide.md) | **NEW**: Prometheus metrics, Grafana dashboard setup, Alertmanager rules, SLO/SLI definitions, health check endpoints |
| [Examples](examples/) | Usage examples for OpenAI, Anthropic, LM Studio, Ollama, etc. |

---

### Project Status

| Item | Status |
|------|--------|
| Version | 1.0.0 (Production/Stable) |
| Python Support | 3.11, 3.12 |
| Test Coverage | 390+ tests, **92%** coverage |
| Type Check | mypy -- strict ✓ |
| Linting | Ruff ✓ |
| CI/CD | GitHub Actions ✓ |
| License | MIT |
| Architecture | Single-process only (distributed support planned for v1.1) |

### 🚧 Development Progress (Phase 1: Foundation)

- [x] Type hints with mypy strict mode
- [x] Benchmark tests for middleware latency
- [x] GitHub Actions CI pipeline
- [x] Unified error code system (ErrorCode enum + OnionErrorWithCode)
- [x] Degradation strategy documentation
- [x] Synchronous API wrapper (for Flask/Django/scripts)
- [x] Enhanced sync API with event loop safety (v0.7.0)
- [x] Response cache middleware (v0.7.0)
- [x] Comprehensive load testing suite (v0.7.0)
- [x] Migration guide and updated docs (v0.7.0)
- [x] 92% test coverage (Phase 1 target: 95% for v1.0)
- [x] Input validation & DoS protection (v0.7.1)
- [x] Refactored sync API to eliminate code duplication (v0.7.1)
- [x] Fixed exception chain preservation issue (v0.7.1)
- [x] Enhanced prompt injection detection with multilingual keywords (v0.7.2)
- [x] Fixed Python version classifier inconsistency (v0.7.2)
- [x] Cache short-circuit optimization - skip provider call on cache hit (v0.7.3)
- [x] Fixed stream_sync memory leak - generator bridge pattern (v0.7.3)
- [x] Added max_stream_chunks config for DoS protection (v0.7.3)
- [x] Enhanced input validation - Unicode bomb detection & nesting depth (v0.7.4)
- [x] Health check HTTP server for Kubernetes probes (v0.7.4)
- [x] Comprehensive monitoring guide with Grafana dashboard JSON (v0.7.4)
- [x] **Architecture consolidation: removed `src/`, unified models and runtime into `onion_core/` (v0.8.0)**
- [x] **Distributed middleware enhancements: token cost tracking, P95/P99 latency, layered rate limiting (v0.9.0)**
- [x] **Critical stability fixes: Unicode confusion false positives, race conditions, OOM prevention (v0.9.1)**
- [x] **Redis connection timeouts, context injection, capped backoff (v0.9.2)**
- [x] **Async improvements: non-blocking tiktoken, cache hit exception safety (v0.9.3)**
- [x] **Anthropic streaming tool calls, accurate token estimation, TCP leak fix (v0.9.4)**
- [x] **Tool calls depth tracking, result size limits, trace ID hierarchy (v0.9.5)**
- [x] **Request total timeout, cache invalidation, TOCTOU documentation (v0.9.6)**
- [x] **Integration & E2E test suite added (v1.0.0)**

### 📋 Roadmap

| Phase | Target | Status |
|-------|--------|--------|
| Phase 1 | Foundation & Standardization | ✅ Complete |
| Phase 2 | Performance Optimization | 🔄 Planned |
| Phase 3 | Advanced Features | 🔄 Planned |
| v1.0 | Production Ready | 🔄 Planned |

> ⚠️ **Note:** This is a **Production/Stable** release (v1.0.0). APIs are stable and backward compatible.
> 
> ⚠️ **Architecture Limitation:** Current version supports **single-process deployment only**. Circuit breaker and rate limiter states are stored in-memory and cannot be shared across multiple instances. Distributed backends (Redis/Etcd) are available via separate middleware classes but require external infrastructure.

### Known Limitations

#### Anthropic Streaming Tool Calls
- Anthropic's streaming API has limited support for complex tool call scenarios. While basic tool use works (`ContentBlockDeltaEvent` with `input_json_delta`), multi-turn tool conversations may experience edge cases where partial JSON fragments need manual assembly.
- **Workaround**: For production tool-heavy workflows, consider using `complete()` instead of `stream()` with Anthropic models, or use OpenAI-compatible providers which have more mature streaming tool call support.

#### Distributed Consistency
- The distributed middlewares (`DistributedRateLimitMiddleware`, `DistributedCacheMiddleware`, `DistributedCircuitBreakerMiddleware`) use Redis as backend but implement **eventual consistency**, not strong consistency.
- **TOCTOU Race Condition**: There is a small time window between checking circuit breaker state and recording success/failure where concurrent requests may slip through during state transitions (CLOSED → OPEN). This is by design to prioritize availability over consistency.
- **Cache Invalidation Lag**: Distributed cache uses TTL-based expiration without active invalidation propagation. Manual `invalidate()` calls only affect the local instance; other instances will see stale data until TTL expires.
- **Recommendation**: For applications requiring strong consistency, implement application-level idempotency keys and accept eventual consistency for non-critical paths.

#### Sync API Limitations
- Synchronous methods (`run_sync()`, `stream_sync()`) **cannot** be called from within an async context (will raise `RuntimeError`).
- `stream_sync()` collects all chunks in memory before yielding (bounded by `max_stream_chunks`, default 10,000), which may cause higher memory usage for very long responses.
- **Recommendation**: Always prefer async methods (`await pipeline.run()`, `async for chunk in pipeline.stream()`) in async applications for better performance and lower memory footprint.

---

### Contributing

Contributions are welcome!

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

### License

Released under the [MIT License](LICENSE).

---

## 中文

### 概述

**Onion Core** 是一个为 AI Agent 打造的中间件框架。它就像给你的大模型应用穿上了一层层"洋葱皮"，每一层都为你的 Agent 提供 **安全、可靠和可观测** 的能力。

```
        用户请求 (Request)
             │
             ▼
    ┌─────────────────────────┐
    │  [1] 链路追踪 (50)       │◄── 外层
    │  [2] 性能监控 (90)       │
    │  [3] 可观测   (100)     │
    │  [4] 限流保护 (150)      │
    │  [5] 安全护栏 (200)      │
    │  [6] 上下文   (300)      │
    └──────────┬──────────────┘
               │
               ▼
          [ 🤖 大模型调用 ]
               │
               ▼
    ┌─────────────────────────┐
    │  [6] 上下文   (300)      │
    │  [5] 安全脱敏 (200)      │
    │  [4] 限流计数 (150)      │
    │  [3] 耗时统计 (100)      │
    │  [2] 指标上报 (90)       │
    │  [1] 链路结束 (50)       │◄── 内层
    └──────────┬──────────────┘
               │
               ▼
        最终响应 (Response)
```

---

### 为什么选择 Onion Core？

开发一个简单的对话机器人很简单，但开发一个**生产级别**的 AI 应用却很难。Onion Core 专门解决这些"脏活累活"：

| 痛点 | Onion Core 解决方案 |
|------|---------------------|
| **安全焦虑** — 提示词注入、隐私泄露 | `SafetyGuardrailMiddleware`：关键词拦截、PII 脱敏（邮箱、手机号、身份证） |
| **成本失控** — Token 爆炸、上下文溢出 | `ContextWindowMiddleware`：tiktoken 精准计数、自动裁剪 |
| **服务不稳定** — API 超时、限流 | 指数退避重试 + Fallback Providers + 熔断机制 |
| **黑盒运行** — 无可见性 | 结构化 JSON 日志、Prometheus 指标、OpenTelemetry 链路追踪 |

---

### 快速开始

#### 安装

```bash
# 基础安装
pip install onion-core

# 含 OpenAI / 国内 AI（DeepSeek、智谱、Kimi、通义）
pip install "onion-core[openai]"

# 含 Anthropic
pip install "onion-core[anthropic]"

# 全家桶
pip install "onion-core[all]"
```

#### 你的第一个安全 Pipeline

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message, EchoProvider
from onion_core.middlewares import (
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
    ObservabilityMiddleware,
)

async def main():
    async with Pipeline(
        provider=EchoProvider(),
        max_retries=2,
        enable_circuit_breaker=True,
    ) as p:
        p.add_middleware(ObservabilityMiddleware())
        p.add_middleware(SafetyGuardrailMiddleware())
        p.add_middleware(ContextWindowMiddleware(max_tokens=2000))

        ctx = AgentContext(messages=[
            Message(role="user", content="我的手机号是 13812345678")
        ])
        response = await p.run(ctx)
        print(response.content)
        # 输出：Echo: 我的手机号是 ***127899999

if __name__ == "__main__":
    asyncio.run(main())
```

#### 同步 API（适用于 Flask/Django/脚本）

> **⚠️ 重要限制：**
> - 同步方法**不能**在 async 上下文中调用（会抛出 `RuntimeError`）
> - `stream_sync()` 会在 yield 之前将所有 chunks 收集到内存中（受 `max_stream_chunks` 限制，默认 10,000）
> - 在异步应用中为了最佳性能，请始终使用 `await pipeline.run()` 和 `async for chunk in pipeline.stream()`

```python
from onion_core import Pipeline, AgentContext, Message, EchoProvider
from onion_core.middlewares import (
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
    ObservabilityMiddleware,
)

# 使用同步上下文管理器
with Pipeline(
    provider=EchoProvider(),
    max_retries=2,
    enable_circuit_breaker=True,
) as p:
    p.add_middleware(ObservabilityMiddleware())
    p.add_middleware(SafetyGuardrailMiddleware())
    p.add_middleware(ContextWindowMiddleware(max_tokens=2000))

    ctx = AgentContext(messages=[
        Message(role="user", content="我的手机号是 13812345678")
    ])
    response = p.run_sync(ctx)  # 注意：使用 run_sync 而非 await p.run()
    print(response.content)
    # 输出：Echo: 我的手机号是 ***127899999

# 流式也有同步版本
with Pipeline(provider=EchoProvider()) as p:
    ctx = AgentContext(messages=[Message(role="user", content="你好")])
    for chunk in p.stream_sync(ctx):  # 注意：使用 stream_sync 而非 p.stream()
        if chunk.delta:
            print(chunk.delta, end="", flush=True)
```

---

### 核心功能

#### 🛡️ 安全护栏
- 内置提示词注入（Prompt Injection）检测
- PII 脱敏：邮箱、手机号（国内/国际）、身份证、信用卡
- 流式无感脱敏（极低延迟）
- 工具调用黑名单

#### 🌏 国内 AI 支持
```python
from onion_core.providers.domestic import DeepSeekProvider, ZhipuAIProvider

provider = DeepSeekProvider(api_key="sk-...")   # DeepSeek V3/R1
provider = ZhipuAIProvider(api_key="...")        # 智谱 GLM-4
```

#### 🏠 本地 / 自建 AI 支持
```python
from onion_core.providers.local import OllamaProvider, LMStudioProvider

provider = OllamaProvider(model="llama3")                    # localhost:11434
provider = LMStudioProvider()                                  # localhost:1234
provider = LocalProvider(base_url="http://192.168.1.100:8000/v1")  # vLLM 等
```

#### 📏 上下文窗口管理
- 使用 `tiktoken` 实现与 OpenAI 完全一致的 Token 计数
- 智能裁剪：自动保留系统提示词 + 最新 N 轮对话

#### ⚡ 限流与熔断
- 按用户（Session ID）滑动窗口限流（内存态，单进程）
- 熔断器：持续故障时自动切断（CLOSED → OPEN → HALF_OPEN → CLOSED）
- **注意**：分布式后端（Redis/Etcd）计划在 v1.0 中实现

#### 📊 生产级可观测
- 带 `request_id` 的结构化 JSON 日志
- Prometheus 指标（`onion_requests_total`、`onion_request_duration_seconds` 等）
- OpenTelemetry 分布式链路追踪

#### 🤖 Agent 循环
```python
from onion_core import AgentLoop, ToolRegistry

registry = ToolRegistry()
@registry.register
def get_weather(city: str) -> str:
    return f"{city}天气晴朗"

agent = AgentLoop(pipeline=p, registry=registry)
response = await agent.run(context)
```

---

### 配置指南

环境变量（前缀 `ONION__`）：

```bash
export ONION__PIPELINE__MAX_RETRIES=3
export ONION__CONTEXT_WINDOW__MAX_TOKENS=8000
export ONION__SAFETY__ENABLE_PII_MASKING=true
```

或配置文件（`onion.json` / `onion.yaml`）：

```json
{
  "pipeline": {"max_retries": 3},
  "safety": {"enable_pii_masking": true}
}
```

---

### 文档

| 文档 | 说明 |
|------|------|
| [API 参考手册](docs/api_reference.md) | 所有类和函数的完整签名 |
| [架构设计文档](docs/architecture.md) | 系统设计、数据流、扩展指南 |
| [错误码使用指南](docs/error_code_usage.md) | 如何使用 `ErrorCode` 和 `OnionErrorWithCode` |
| [降级策略文档](docs/degradation_strategy.md) | 重试、熔断、Fallback Provider 链路 |
| [监控与告警指南](docs/monitoring_guide.md) | **新增**: Prometheus 指标、Grafana 仪表板配置、Alertmanager 规则、SLO/SLI 定义、健康检查端点 |
| [示例代码](examples/) | OpenAI、Anthropic、LM Studio、Ollama 等使用示例 |

---

### 项目状态

| 项目 | 状态 |
|------|------|
| 版本 | 1.0.0（Production/Stable） |
| Python 支持 | 3.11、3.12 |
| 测试覆盖 | 390+ 个测试，**92%** 覆盖率 |
| 类型检查 | mypy -- strict ✓ |
| 代码检查 | Ruff ✓ |
| CI/CD | GitHub Actions ✓ |
| 开源协议 | MIT |
| 架构限制 | 仅支持单进程部署（分布式支持计划于 v1.1） |

### 🚧 开发进度（第一阶段：基础与标准化）

- [x] mypy 严格类型检查
- [x] 中间件性能基准测试
- [x] GitHub Actions CI 流水线
- [x] 统一错误码系统（ErrorCode 枚举 + OnionErrorWithCode）
- [x] 降级策略文档
- [x] 同步 API 封装（适用于 Flask/Django/脚本）
- [x] 增强同步 API 事件循环安全性（v0.7.0）
- [x] 响应缓存中间件（v0.7.0）
- [x] 完整压力测试套件（v0.7.0）
- [x] 迁移指南和文档更新（v0.7.0）
- [x] 92% 测试覆盖率（v1.0 目标：95%）
- [x] 输入验证与 DoS 防护（v0.7.1）
- [x] 重构同步 API，消除代码重复（v0.7.1）
- [x] 修复异常链丢失问题（v0.7.1）
- [x] 增强提示词注入检测，支持多语言关键词（v0.7.2）
- [x] 修复 Python 版本分类器不一致问题（v0.7.2）
- [x] 缓存短路优化 - 命中时跳过 Provider 调用（v0.7.3）
- [x] 修复 stream_sync 内存泄漏 - 生成器桥接模式（v0.7.3）
- [x] 添加 max_stream_chunks 配置防止 DoS 攻击（v0.7.3）
- [x] 增强输入验证 - Unicode 炸弹检测和嵌套深度（v0.7.4）
- [x] Kubernetes 探针健康检查 HTTP 服务器（v0.7.4）
- [x] 包含 Grafana Dashboard JSON 的完整监控指南（v0.7.4）
- [x] **架构统一：移除 `src/`，模型和运行时合并到 `onion_core/`（v0.8.0）**
- [x] **分布式中间件增强：Token 成本跟踪、P95/P99 延迟、分层限流（v0.9.0）**
- [x] **关键稳定性修复：Unicode 混淆误报、竞态条件、OOM 预防（v0.9.1）**
- [x] **Redis 连接超时、上下文注入、退避上限（v0.9.2）**
- [x] **异步改进：非阻塞 tiktoken、缓存命中异常安全（v0.9.3）**
- [x] **Anthropic 流式工具调用、精准 Token 估算、TCP 泄漏修复（v0.9.4）**
- [x] **工具调用深度跟踪、结果大小限制、Trace ID 层级统一（v0.9.5）**
- [x] **请求总超时、缓存失效、TOCTOU 文档化（v0.9.6）**
- [x] **集成测试和 E2E 测试套件新增（v1.0.0）**

### 📋 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| 第一阶段 | 基础与标准化 | ✅ 已完成 |
| 第二阶段 | 性能优化 | 🔄 计划中 |
| 第三阶段 | 高级功能 | 🔄 计划中 |
| v1.0 | 生产就绪 | 🔄 计划中 |

> ⚠️ **注意：** 当前为 **生产就绪** 版本（v1.0.0）。API 稳定且向后兼容。
>
> ⚠️ **架构限制：** 当前版本**仅支持单进程部署**。熔断器和限流器状态存储在内存中，无法在多个实例间共享。分布式后端（Redis/Etcd）可通过独立的中间件类使用，但需要外部基础设施。

### 已知限制

#### Anthropic 流式工具调用
- Anthropic 的流式 API 对复杂工具调用场景的支持有限。虽然基本工具调用可用（`ContentBlockDeltaEvent` 配合 `input_json_delta`），但在多轮工具对话中可能会遇到部分 JSON 片段需要手动组装的边缘情况。
- **解决方案**：对于生产环境中重度依赖工具调用的工作流，建议对 Anthropic 模型使用 `complete()` 而非 `stream()`，或使用 OpenAI 兼容的 Provider，它们对流式工具调用的支持更成熟。

#### 分布式一致性
- 分布式中间件（`DistributedRateLimitMiddleware`、`DistributedCacheMiddleware`、`DistributedCircuitBreakerMiddleware`）使用 Redis 作为后端，但实现的是**最终一致性**，而非强一致性。
- **TOCTOU 竞态条件**：在检查熔断器状态和记录成功/失败之间存在一个小的时间窗口，并发请求可能在状态转换期间（CLOSED → OPEN）穿透。这是为了优先考虑可用性而非一致性的设计选择。
- **缓存失效延迟**：分布式缓存使用基于 TTL 的过期机制，没有主动的失效传播。手动调用 `invalidate()` 只影响本地实例；其他实例会看到旧数据直到 TTL 过期。
- **建议**：对于需要强一致性的应用，在应用层实现幂等性键，并在非关键路径上接受最终一致性。

#### 同步 API 限制
- 同步方法（`run_sync()`、`stream_sync()`）**不能**在 async 上下文中调用（会抛出 `RuntimeError`）。
- `stream_sync()` 会在 yield 之前将所有 chunks 收集到内存中（受 `max_stream_chunks` 限制，默认 10,000），这可能导致非常长的响应占用更多内存。
- **建议**：在异步应用中始终优先使用异步方法（`await pipeline.run()`、`async for chunk in pipeline.stream()`）以获得更好的性能和更低的内存占用。

---

### 参与贡献

欢迎贡献！

1. Fork 本仓库
2. 创建特性分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m 'Add amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 开启 Pull Request

---

### 许可证

基于 [MIT 许可证](LICENSE) 开源。
