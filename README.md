# 🧅 Onion Core

<div align="center">

**Agent Middleware Framework — Onion-Model Pipeline for LLM Applications**

[![Version](https://img.shields.io/badge/version-0.5.0-blue.svg)](https://github.com/0z2w2j1/onion-core)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Test Status](https://github.com/0z2w2j1/onion-core/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/0z2w2j1/onion-core/actions)
[![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen.svg)]()
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

---

### Core Features

#### 🛡️ Security Guardrail
- Built-in prompt injection detection
- PII masking: email, China phone, intl phone, ID card, credit card
- Streaming PII masking (minimal latency)
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
- Auto-truncation: preserves system prompt + latest N rounds

#### ⚡ Rate Limiting & Circuit Breaker
- Per-session sliding window rate limiting
- Circuit breaker: stops hitting a failing provider (CLOSED → OPEN → HALF_OPEN → CLOSED)

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
| [Examples](examples/) | Usage examples for OpenAI, Anthropic, LM Studio, Ollama, etc. |

---

### Project Status

| Item | Status |
|------|--------|
| Version | 0.5.0 (Alpha) |
| Python Support | 3.11, 3.12 |
| Test Coverage | 194+ tests, 85% coverage |
| Type Check | mypy -- strict ✓ |
| Linting | Ruff ✓ |
| CI/CD | GitHub Actions ✓ |
| License | MIT |

### 🚧 Development Progress (Phase 1: Foundation)

- [x] Type hints with mypy strict mode
- [x] Benchmark tests for middleware latency
- [x] GitHub Actions CI pipeline
- [x] Unified error code system (ErrorCode enum + OnionErrorWithCode)
- [x] Degradation strategy documentation
- [x] 85% test coverage (Phase 1 target: 90% for v1.0)

### 📋 Roadmap

| Phase | Target | Status |
|-------|--------|--------|
| Phase 1 | Foundation & Standardization | ✅ Complete |
| Phase 2 | Performance Optimization | 🔄 Planned |
| Phase 3 | Advanced Features | 🔄 Planned |
| v1.0 | Production Ready | 🔄 Planned |

> ⚠️ **Note:** This is an alpha release. APIs may change without notice until v1.0.

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
- 按用户（Session ID）滑动窗口限流
- 熔断器：持续故障时自动切断（CLOSED → OPEN → HALF_OPEN → CLOSED）

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
| [示例代码](examples/) | OpenAI、Anthropic、LM Studio、Ollama 等使用示例 |

---

### 项目状态

| 项目 | 状态 |
|------|------|
| 版本 | 0.5.0（Alpha） |
| Python 支持 | 3.11、3.12 |
| 测试覆盖 | 194+ 个测试，85% 覆盖率 |
| 类型检查 | mypy -- strict ✓ |
| 代码检查 | Ruff ✓ |
| CI/CD | GitHub Actions ✓ |
| 开源协议 | MIT |

### 🚧 开发进度（第一阶段：基础与标准化）

- [x] mypy 严格类型检查
- [x] 中间件性能基准测试
- [x] GitHub Actions CI 流水线
- [x] 统一错误码系统（ErrorCode 枚举 + OnionErrorWithCode）
- [x] 降级策略文档
- [x] 85% 测试覆盖率（v1.0 目标：90%）

### 📋 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| 第一阶段 | 基础与标准化 | ✅ 已完成 |
| 第二阶段 | 性能优化 | 🔄 计划中 |
| 第三阶段 | 高级功能 | 🔄 计划中 |
| v1.0 | 生产就绪 | 🔄 计划中 |

> ⚠️ **注意：** 当前为 Alpha 版本，API 可能在 v1.0 之前发生变化。

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
