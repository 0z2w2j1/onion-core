# Onion Core Documentation

> **Agent middleware framework** — onion-model pipeline for LLM applications

[![PyPI version](https://badge.fury.io/py/onion-core.svg)](https://badge.fury.io/py/onion-core)
[![Python Support](https://img.shields.io/pypi/pyversions/onion-core.svg)](https://pypi.org/project/onion-core/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🧅 What is Onion Core?

Onion Core is a **middleware framework** for building reliable, secure, and observable AI Agent applications. It wraps LLM calls with layered protective middleware, following the principle of **defense in depth**.

```
                    ┌─────────────────────────────┐
                    │         User Request         │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────┐
              │  [1] Tracing     (priority=50)        │ ◄── Outer
              │  [2] Metrics     (priority=90)        │
              │  [3] Observability(priority=100)      │
              │  [4] Rate Limit  (priority=150)       │
              │  [5] Safety      (priority=200)       │
              │  [6] Context     (priority=300)       │
              └──────────────┬───────────────────────┘
                             │
                             ▼
                    [ LLM Provider Call ]
                             │
                             ▼
              ┌────────────────────────────────────────┐
              │  [6] Context     (priority=300)       │
              │  [5] Safety      (priority=200)       │
              │  [4] Rate Limit  (priority=150)       │
              │  [3] Observability(priority=100)      │
              │  [2] Metrics     (priority=90)        │
              │  [1] Tracing     (priority=50)        │ ◄── Inner
              └──────────────┬───────────────────────┘
                             │
                             ▼
                    ┌─────────────────────────────┐
                    │        User Response          │
                    └─────────────────────────────┘
```

## 🚀 Quick Start

### Installation

```bash
pip install onion-core
```

### Basic Usage

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message, EchoProvider

async def main():
    async with Pipeline(provider=EchoProvider()) as p:
        ctx = AgentContext(messages=[
            Message(role="user", content="Hello, Onion Core!")
        ])
        
        response = await p.run(ctx)
        print(response.content)

if __name__ == "__main__":
    asyncio.run(main())
```

## 📚 Documentation Structure

This documentation follows the [Diátaxis framework](https://diataxis.fr/):

### 🎓 [Tutorials](tutorials/README.md)
Learning-oriented lessons that guide you through practical exercises.

- [5-Minute Quick Start](tutorials/01-quick-start.md)
- [Build a Secure Agent](tutorials/02-secure-agent.md)
- [Multi-Provider Fallback](tutorials/03-fallback-providers.md)
- [Streaming & Sync API](tutorials/04-streaming-sync.md)

### 🔧 [How-to Guides](how-to-guides/README.md)
Problem-oriented guides to help you solve specific tasks.

- Configure Redis Distributed Rate Limiting
- Customize PII Rules
- Setup Fallback Providers
- Use Sync API in Flask/Django
- Troubleshoot Timeouts

### 📖 [Reference](reference/README.md)
Information-oriented technical descriptions.

- [Pipeline API](reference/pipeline.md)
- [Middlewares API](reference/middlewares.md)
- [Auto-generated API Reference](api/)

### 💡 [Explanation](explanation/README.md)
Understanding-oriented discussions of design decisions.

- [Onion Model Philosophy](explanation/onion-model-philosophy.md)
- [Pipeline Scheduling](explanation/pipeline-scheduling.md)
- [Error Code System](explanation/error-code-system.md)
- [Distributed Consistency](explanation/distributed-consistency.md)

## ✨ Key Features

- **🛡️ Security**: PII masking, prompt injection detection, keyword blocking
- **⚡ Reliability**: Retry with exponential backoff, circuit breaker, fallback providers
- **📊 Observability**: Structured logging, Prometheus metrics, OpenTelemetry tracing
- **🔄 Flexibility**: Provider-agnostic, middleware extensibility, async-first design
- **🌐 Distributed**: Redis-based rate limiting, caching, and circuit breaking

## 🤝 Contributing

Contributions are welcome! Please read our [Contributing Guide](https://github.com/0z2w2j1/onion-core/blob/main/CONTRIBUTING.md) for details.

## 📄 License

Released under the [MIT License](https://github.com/0z2w2j1/onion-core/blob/main/LICENSE).

---

**Ready to get started?** Check out the [Quick Start Tutorial](tutorials/01-quick-start.md)! 🚀
