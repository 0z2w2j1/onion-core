# 🧅 Onion Core

<div align="center">

**Lightweight Embeddable Middleware Layer for LLM Call Governance**

[![Version](https://img.shields.io/badge/version-1.1.0b1-blue.svg)](https://github.com/0z2w2j1/onion-core)
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

**Onion Core** is a lightweight middleware layer for governing LLM calls. It wraps an existing provider or SDK call with layered "onion skins" for **safety, rate limiting, caching, budget control, context control, retries, fallback, and observability**.

```
         User Request
              │
              ▼
     ┌─────────────────────────┐
     │ [1] Tracing    (50)     │◄── Outer
     │ [2] Cache      (75)     │
     │ [3] Metrics    (90)     │
     │ [4] Observability(100)  │
     │ [5] Rate Limit (150)    │
     │ [6] Safety     (200)    │
     │ [7] Context    (300)    │
     └──────────┬──────────────┘
                │
                ▼
           [ LLM Provider ]
                │
                ▼
     ┌─────────────────────────┐
     │ [7] Context    (300)    │
     │ [6] Safety     (200)    │
     │ [5] Rate Limit (150)    │
     │ [4] Observability(100)   │
     │ [3] Metrics    (90)     │
     │ [2] Cache      (75)     │
     │ [1] Tracing    (50)     │◄── Inner
     └──────────┬──────────────┘
                │
                ▼
         Final Response
```

---

### Why Onion Core?

Onion Core is for teams that already have an LLM call path and want operational guardrails without adopting a full agent framework:

| Problem | Onion Core Solution |
|---------|---------------------|
| **Security anxiety** — prompt injection, PII leakage | `SafetyGuardrailMiddleware`: keyword blocking, PII masking (email, phone, ID) |
| **Cost control** — token explosion, context overflow | `ContextWindowMiddleware` + `BudgetMiddleware`: token counting, truncation, quota enforcement |
| **Service instability** — API timeouts, rate limits | Retry with exponential backoff + Fallback Providers + Circuit Breaker |
| **Repeated calls** — redundant LLM API cost | `ResponseCacheMiddleware`: LRU cache with TTL, SHA-256 key matching |
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

#### Your First Governed Pipeline

```python
import asyncio
from onion_core import EchoProvider, Pipeline

async def main():
    async with Pipeline.governed(
        provider=EchoProvider(reply=None),
        preset="balanced",  # cache + logging + rate limit + safety + context window
    ) as p:
        response = await p.complete("My phone is 13812345678")
        print(response.content)
        # Output: Echo: My phone is ***

if __name__ == "__main__":
    asyncio.run(main())
```

#### Wrap an Existing LLM Call

```python
from onion_core import AgentContext, CallableProvider, Pipeline

async def existing_llm_call(ctx: AgentContext) -> str:
    # Call your current SDK/client here.
    return f"LLM saw: {ctx.messages[-1].text_content}"

pipeline = Pipeline.governed(
    provider=CallableProvider(existing_llm_call, model="my-existing-model"),
    preset="balanced",
)

response = await pipeline.complete("hello")
```

#### Synchronous API (for Flask/Django/Scripts)

> **⚠️ Important Limitations:**
> - Sync methods **cannot** be called from within an async context (will raise `RuntimeError`)
> - `stream_sync()` uses a producer-thread + queue pattern for streaming; chunks are yielded one-by-one (not fully buffered)
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
    provider=EchoProvider(reply=None),
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
    # Output: Echo: My phone is ***

# Streaming also has sync version
with Pipeline(provider=EchoProvider(reply=None)) as p:
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

#### 💸 Budget Governance
- `BudgetMiddleware` enforces sliding-window token and cost budgets
- Scope by tenant, session, API key, or any metadata/config key
- Budget checks happen before provider calls; usage is recorded from provider token stats

#### ⚡ Rate Limiting & Circuit Breaker
- **Layered rate limiting**: Separate limits for regular requests vs tool calls (prevents tool call storms)
- Per-session sliding window (in-memory, single-process)
- Circuit breaker: stops hitting a failing provider (CLOSED → OPEN → HALF_OPEN → CLOSED)
- **Note**: Redis-backed distributed middlewares are available as optional components

#### 📊 Operational Observability
- Structured JSON logging with `request_id`
- Prometheus metrics (`onion_requests_total`, `onion_request_duration_seconds`, etc.)
- OpenTelemetry distributed tracing

#### 🤖 Experimental Agent Loop

Onion Core includes a small AgentLoop/AgentRuntime for examples and simple tool loops, but the primary public path is the embeddable middleware pipeline.

```python
from onion_core import AgentLoop
from onion_core.tools import ToolRegistry

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

### Documentation (Diátaxis Framework)

We organize our documentation following the [Diátaxis framework](https://diataxis.fr/):

#### 🎓 [Tutorials](docs/tutorials/) - Learning-oriented
- [5-Minute Quick Start](docs/tutorials/01-quick-start.md) - Install and run your first Pipeline
- [Build a Secure Agent](docs/tutorials/02-secure-agent.md) - Add PII masking, injection detection, and context management

#### 🔧 [How-to Guides](docs/how-to-guides/) - Problem-oriented
- [Configure Redis Distributed Rate Limiting](docs/how-to-guides/configure-distributed-ratelimit.md)
- [Customize PII Rules](docs/how-to-guides/custom-pii-rules.md)
- [Setup Fallback Providers](docs/how-to-guides/setup-fallback-providers.md)
- [Production Deployment Checklist](docs/how-to-guides/production-deployment.md)
- [Use Sync API in Flask/Django](docs/how-to-guides/use-sync-api-in-web-frameworks.md)

#### 📚 [Reference](docs/reference/) - Information-oriented
- [API Reference](docs/reference/README.md) - Public API entry points and generated references
- [API Stability Policy](docs/reference/api-stability.md) - Stable vs beta public APIs
- [Provider Contract](docs/reference/provider-contract.md) - Requirements for provider adapters
- [Error Codes](docs/explanation/error-code-system.md) - Error codes and retry policies
- [Configuration Options](docs/how-to-guides/load-config-from-file.md) - Config file loading and options

#### 💡 [Explanation](docs/explanation/) - Understanding-oriented
- [Onion Model Philosophy](docs/explanation/onion-model-philosophy.md) - Why onion architecture?
- [Pipeline Scheduling](docs/explanation/pipeline-scheduling.md) - How requests flow through middleware
- [Distributed Consistency](docs/explanation/distributed-consistency.md) - TOCTOU and eventual consistency

The public documentation is centered on tutorials, how-to guides, reference, and explanation pages. Historical design notes are kept out of the published site.

---

### Project Status

| Item | Status |
|------|--------|
| Version | 1.1.0b1 (Beta, governance-layer focus) |
| Python Support | 3.11, 3.12 |
| Test Coverage | 500+ tests, **86%+** coverage |
| Type Check | mypy -- strict ✓ |
| Linting | Ruff ✓ |
| CI/CD | GitHub Actions ✓ |
| License | MIT |
| Architecture | Embeddable single-process middleware layer; optional Redis-backed coordination components |

### 📋 Roadmap

| Phase | Target | Status |
|-------|--------|--------|
| Phase 1 | Foundation & Standardization | ✅ Complete |
| Phase 2 | Lightweight governance-layer focus | 🚧 Active |

Current focus:
- Keep the public path centered on `Pipeline`, `LLMProvider`, and governance middleware.
- Treat AgentLoop/AgentRuntime as optional/experimental helpers, not the main product surface.
- Improve provider/model-safe caching, budget enforcement, Redis integration tests, and embedding guides.
> 
> ⚠️ **Architecture Limitation:** The default middlewares are single-process and in-memory. Redis-backed distributed middlewares are available as optional components and require external infrastructure.

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
- `stream_sync()` uses a producer-thread + queue pattern for streaming; chunks are passed one-by-one through a thread-safe queue. The `max_stream_chunks` parameter (default 10,000) acts as a DoS safety limit on total chunk count.
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

**Onion Core** 是一个轻量、可嵌入的 LLM 调用治理中间件层。它可以包裹你现有的 Provider 或 SDK 调用，用一层层"洋葱皮"提供 **安全、限流、缓存、预算、上下文控制、重试、降级和可观测** 能力。

```
        用户请求 (Request)
             │
             ▼
    ┌─────────────────────────┐
     │  [1] 链路追踪 (50)       │◄── 外层
     │  [2] 缓存     (75)      │
     │  [3] 性能监控 (90)       │
     │  [4] 可观测   (100)     │
     │  [5] 限流保护 (150)      │
     │  [6] 安全护栏 (200)      │
     │  [7] 上下文   (300)      │
    └──────────┬──────────────┘
               │
               ▼
          [ 🤖 大模型调用 ]
               │
               ▼
    ┌─────────────────────────┐
     │  [7] 上下文   (300)      │
     │  [6] 安全脱敏 (200)      │
     │  [5] 限流计数 (150)      │
     │  [4] 耗时统计 (100)      │
     │  [3] 指标上报 (90)       │
     │  [2] 缓存命中 (75)       │
     │  [1] 链路结束 (50)       │◄── 内层
    └──────────┬──────────────┘
               │
               ▼
        最终响应 (Response)
```

---

### 为什么选择 Onion Core？

Onion Core 适合已经有 LLM 调用链路、但希望低成本加上运行时治理能力的团队：

| 痛点 | Onion Core 解决方案 |
|------|---------------------|
| **安全焦虑** — 提示词注入、隐私泄露 | `SafetyGuardrailMiddleware`：关键词拦截、PII 脱敏（邮箱、手机号、身份证） |
| **成本失控** — Token 爆炸、上下文溢出 | `ContextWindowMiddleware` + `BudgetMiddleware`：Token 计数、裁剪、预算拦截 |
| **服务不稳定** — API 超时、限流 | 指数退避重试 + Fallback Providers + 熔断机制 |
| **重复调用** — 冗余的 LLM API 成本 | `ResponseCacheMiddleware`：带 TTL 的 LRU 缓存，SHA-256 键匹配 |
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

#### 第一个治理型 Pipeline

```python
import asyncio
from onion_core import EchoProvider, Pipeline

async def main():
    async with Pipeline.governed(
        provider=EchoProvider(reply=None),
        preset="balanced",  # 缓存 + 日志 + 限流 + 安全 + 上下文窗口
    ) as p:
        response = await p.complete("我的手机号是 13812345678")
        print(response.content)
        # 输出：Echo: 我的手机号是 ***

if __name__ == "__main__":
    asyncio.run(main())
```

#### 包裹已有 LLM 调用

```python
from onion_core import AgentContext, CallableProvider, Pipeline

async def existing_llm_call(ctx: AgentContext) -> str:
    # 在这里调用你当前已经在用的 SDK/client。
    return f"LLM saw: {ctx.messages[-1].text_content}"

pipeline = Pipeline.governed(
    provider=CallableProvider(existing_llm_call, model="my-existing-model"),
    preset="balanced",
)

response = await pipeline.complete("hello")
```

#### 同步 API（适用于 Flask/Django/脚本）

> **⚠️ 重要限制：**
> - 同步方法**不能**在 async 上下文中调用（会抛出 `RuntimeError`）
> - `stream_sync()` 使用生产者线程+队列模式进行流式传输，chunks 逐个产出（非全部缓冲）
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
    provider=EchoProvider(reply=None),
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
with Pipeline(provider=EchoProvider(reply=None)) as p:
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

#### 💸 预算治理
- `BudgetMiddleware` 支持滑动窗口 Token/成本预算
- 可按租户、session、API key 或自定义 metadata/config key 限额
- Provider 调用前先检查预算，调用后根据 usage 记录消耗

#### ⚡ 限流与熔断
- 按用户（Session ID）滑动窗口限流（内存态，单进程）
- 熔断器：持续故障时自动切断（CLOSED → OPEN → HALF_OPEN → CLOSED）
- **注意**：Redis 支持的分布式中间件已可用（可选组件）

#### 📊 生产级可观测
- 带 `request_id` 的结构化 JSON 日志
- Prometheus 指标（`onion_requests_total`、`onion_request_duration_seconds` 等）
- OpenTelemetry 分布式链路追踪

#### 🤖 实验性 Agent 循环

项目保留了轻量的 AgentLoop/AgentRuntime，适合示例和简单工具循环；主要公开路径仍是可嵌入的 middleware pipeline。

```python
from onion_core import AgentLoop
from onion_core.tools import ToolRegistry

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

### 文档（Diátaxis 框架）

我们按照 [Diátaxis 框架](https://diataxis.fr/) 组织文档：

#### 🎓 [教程](docs/tutorials/) - 学习导向
- [5分钟快速入门](docs/tutorials/01-quick-start.md) - 安装并运行第一个 Pipeline
- [构建安全 Agent](docs/tutorials/02-secure-agent.md) - 添加 PII 脱敏、注入检测和上下文管理

#### 🔧 [操作指南](docs/how-to-guides/) - 问题导向
- [配置 Redis 分布式限流](docs/how-to-guides/configure-distributed-ratelimit.md)
- [自定义 PII 规则](docs/how-to-guides/custom-pii-rules.md)
- [设置 Fallback Providers](docs/how-to-guides/setup-fallback-providers.md)
- [在 Flask/Django 中使用同步 API](docs/how-to-guides/use-sync-api-in-web-frameworks.md)

#### 📚 [参考手册](docs/reference/) - 信息导向
- [API 参考](docs/reference/README.md) - 公共 API 入口和自动生成参考
- [错误码](docs/explanation/error-code-system.md) - 错误码和重试策略
- [配置选项](docs/how-to-guides/load-config-from-file.md) - 配置文件的加载与选项说明

#### 💡 [背景解释](docs/explanation/) - 理解导向
- [洋葱模型设计哲学](docs/explanation/onion-model-philosophy.md) - 为什么选择洋葱架构？
- [Pipeline 调度引擎](docs/explanation/pipeline-scheduling.md) - 请求如何在中间件间流转
- [分布式一致性](docs/explanation/distributed-consistency.md) - TOCTOU 与最终一致性

公开文档以教程、操作指南、参考手册和解释文档为主；历史设计笔记不会进入发布站点。

---

### 项目状态

| 项目 | 状态 |
|------|------|
| 版本 | 1.1.0b1（Beta，聚焦治理层） |
| Python 支持 | 3.11、3.12 |
| 测试覆盖 | 500+ 个测试，**86%+** 覆盖率 |
| 类型检查 | mypy -- strict ✓ |
| 代码检查 | Ruff ✓ |
| CI/CD | GitHub Actions ✓ |
| 开源协议 | MIT |
| 架构限制 | 可嵌入的单进程中间件层，可选 Redis 分布式协调组件 |

### 📋 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| 第一阶段 | 基础与标准化 | ✅ 已完成 |
| 第二阶段 | 轻量 LLM 调用治理层 | 🚧 进行中 |

当前重点：
- 将主要公开路径收敛到 `Pipeline`、`LLMProvider` 和治理中间件。
- 将 AgentLoop/AgentRuntime 作为可选/实验性能力，而非主产品面。
- 继续加强 provider/model 安全缓存、预算拦截、Redis 集成测试和嵌入式使用指南。
>
> ⚠️ **架构限制：** 默认中间件为单进程内存态。Redis 分布式中间件作为可选组件提供，需要外部基础设施。

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
- `stream_sync()` 使用生产者线程+队列模式进行流式传输，chunks 通过线程安全队列逐个传递。`max_stream_chunks` 参数（默认 10,000）作为 DoS 安全限制，限制总 chunk 数量。
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
