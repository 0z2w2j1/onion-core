# Contributing to Onion Core

Thank you for your interest in contributing to Onion Core! This document provides guidelines and workflows for contributing.

> **Note:** This project is Production/Stable (v1.0.0). APIs are stable and backward compatible.

---

## How to Contribute

### Reporting Issues

- Use [GitHub Issues](https://github.com/0z2w2j1/onion-core/issues) to report bugs or request features
- Include: expected behavior, actual behavior, reproduction steps, environment info

### Pull Request Workflow

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Develop** your changes
4. **Test** locally (see Testing section below)
5. **Commit** with clear messages (`git commit -m 'Add amazing feature'`)
6. **Push** to your fork (`git push origin feature/amazing-feature`)
7. **Open** a Pull Request against the `main` branch

---

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/Onion-Core.git
cd Onion-Core

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

---

## Code Standards

### Linting & Formatting

```bash
# Run ruff linter
ruff check onion_core/

# Auto-fix issues
ruff check --fix onion_core/
```

### Type Checking

```bash
# Run mypy in strict mode
mypy onion_core/
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=onion_core --cov-report=term-missing

# Run a specific test file
pytest tests/test_pipeline.py
```

---

## Project Structure Guidelines

```
onion_core/
├── middlewares/    # Add new middleware here
├── providers/      # Add new LLM provider adapters here
├── observability/  # Tracing, metrics, logging
├── tools.py        # Tool registry
├── agent.py        # Agent loop
└── pipeline.py     # Core orchestrator
```

### Adding a New Middleware

1. Create a class extending `BaseMiddleware` (`onion_core/base.py`)
2. Implement `async process_request()` / `process_response()` / `process_stream_chunk()`
3. Set `priority` (lower = runs earlier in request phase)
4. Add tests in `tests/` directory
5. Export in `onion_core/middlewares/__init__.py`

### Adding a New Provider

1. Create a class extending `LLMProvider` (`onion_core/provider.py`)
2. Implement `async complete()` and `async stream()`
3. Optionally implement `async cleanup()` for resource lifecycle
4. Add tests in `tests/`
5. Export in `onion_core/providers/__init__.py`

---

## Commit Message Convention

Use clear, descriptive commit messages:

```
feat: add token budget middleware
fix: correct circuit breaker state transition
docs: update API reference for Pipeline
test: add edge cases for PII masking
refactor: simplify retry logic in pipeline
```

---

## Error Codes

When adding new error types, follow the unified error code system in `onion_core/error_codes.py`:

- Add the code with a unique integer
- Define `RetryPolicy` (RETRY / FALLBACK / FATAL)
- Document in `docs/error_code_usage.md`

---

## Questions?

Feel free to open a GitHub Issue for any questions about contributing.

---

# 贡献指南

感谢您对 Onion Core 的关注！本文档提供贡献指南和工作流程。

> **注意：** 此项目处于 Production/Stable 阶段（v1.0.0）。API 稳定且向后兼容。

---

## 如何贡献

### 报告问题

- 使用 [GitHub Issues](https://github.com/0z2w2j1/onion-core/issues) 报告bugs或请求新功能
- 包含：预期行为、实际行为、重现步骤、 环境信息

### Pull Request 工作流程

1. **Fork** 仓库
2. **创建** 功能分支（`git checkout -b feature/amazing-feature`）
3. **开发** 您的更改
4. **本地测试**（参见下方测试部分）
5. **提交** 清晰的提交信息（`git commit -m 'Add amazing feature'`）
6. **推送** 到您的fork（`git push origin feature/amazing-feature`）
7. **开启** Pull Request 到 `main` 分支

---

## 开发环境设置

```bash
# 克隆您的 fork
git clone https://github.com/YOUR_USERNAME/Onion-Core.git
cd Onion-Core

# 以可编辑模式安装，包含开发依赖
pip install -e ".[dev]"
```

---

## 代码规范

### 代码检查与格式化

```bash
# 运行 ruff linter
ruff check onion_core/

# 自动修复问题
ruff check --fix onion_core/
```

### 类型检查

```bash
# 严格模式运行 mypy
mypy onion_core/
```

### 测试

```bash
# 运行所有测试
pytest

# 运行并生成覆盖率报告
pytest --cov=onion_core --cov-report=term-missing

# 运行特定测试文件
pytest tests/test_pipeline.py
```

---

## 项目结构指南

```
onion_core/
├── middlewares/    # 在此添加新中间件
├── providers/      # 在此添加新 LLM Provider 适配器
├── observability/  # 链路追踪、指标、日志
├── tools.py        # 工具注册
├── agent.py        # Agent 循环
└── pipeline.py     # 核心调度器
```

### 添加新中间件

1. 创建继承自 `BaseMiddleware` 的类（`onion_core/base.py`）
2. 实现 `async process_request()` / `process_response()` / `process_stream_chunk()`
3. 设置 `priority`（数值越小，请求阶段越早执行）
4. 在 `tests/` 目录中添加测试
5. 在 `onion_core/middlewares/__init__.py` 中导出

### 添加新 Provider

1. 创建继承自 `LLMProvider` 的类（`onion_core/provider.py`）
2. 实现 `async complete()` 和 `async stream()`
3. 可选实现 `async cleanup()` 用于资源生命周期管理
4. 在 `tests/` 中添加测试
5. 在 `onion_core/providers/__init__.py` 中导出

---

## 提交信息规范

使用清晰、描述性的提交信息：

```
feat: 添加 token 预算中间件
fix: 修复熔断器状态转换
docs: 更新 Pipeline API 参考
test: 添加 PII 脱敏边界用例
refactor: 简化 Pipeline 重试逻辑
```

---

## 错误码

添加新错误类型时，请遵循 `onion_core/error_codes.py` 中的统一错误码系统：

- 使用唯一整数添加错误码
- 定义 `RetryPolicy`（RETRY / FALLBACK / FATAL）
- 在 `docs/error_code_usage.md` 中记录

---

## 问题？

如有关于贡献的任何问题，请随时开启 GitHub Issue。
