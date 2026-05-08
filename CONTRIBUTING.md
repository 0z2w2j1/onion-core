# Contributing to Onion Core

Thank you for helping improve Onion Core. This project is focused on a
lightweight, embeddable governance layer for LLM calls.

Before changing public behavior, read the API stability policy:

- [API Stability Policy](docs/reference/api-stability.md)
- [Provider Contract](docs/reference/provider-contract.md)

## Reporting Issues

Use GitHub Issues for bugs, documentation problems, and feature requests.

For bugs, include:

- Onion Core version
- Python version
- operating system
- provider and model, if relevant
- minimal reproduction
- traceback or error code
- whether Redis or other external services are required

Do not report security issues publicly. Follow [SECURITY.md](SECURITY.md).

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/onion-core.git
cd onion-core
pip install -e ".[all,dev]"
```

## Local Verification

Run these before opening a pull request:

```bash
ruff check .
mypy onion_core --strict
pytest
python -m build
twine check dist/*
```

For documentation changes:

```bash
mkdocs build --strict
```

For Redis-backed changes, also run the real Redis integration tests when Redis
is available:

```bash
set ONION_REDIS_URL=redis://localhost:6379/15
pytest tests/test_redis_integration.py -q
```

## Pull Request Checklist

- Keep the change scoped to one problem.
- Add or update tests for behavior changes.
- Update docs for public API or configuration changes.
- Update `CHANGELOG.md`.
- Document migration notes for breaking or beta API changes.
- Mention Redis, provider, or external-service requirements when relevant.

## Project Structure

```text
onion_core/
  middlewares/      # governance middleware
  providers/        # LLM provider adapters
  observability/    # logging, metrics, tracing
  tools.py          # tool registry
  agent.py          # beta agent runtime helpers
  pipeline.py       # core orchestrator
```

## Adding Middleware

1. Extend `BaseMiddleware`.
2. Implement `process_request()` and `process_response()`.
3. Override stream, tool, or error hooks only when needed.
4. Set a priority that fits the existing middleware order.
5. Mark `is_mandatory=True` only when failure must stop the chain.
6. Add tests for ordering, error behavior, and metadata.
7. Export the middleware from `onion_core/middlewares/__init__.py`.

## Adding Providers

1. Extend `LLMProvider`.
2. Implement `complete()` and `stream()`.
3. Normalize responses into `LLMResponse` and `StreamChunk`.
4. Map upstream failures to Onion provider errors where practical.
5. Implement `cleanup()` when the provider owns network resources.
6. Add mocked unit tests and optional real integration tests.
7. Export the provider from `onion_core/providers/__init__.py`.

## Commit Messages

Use clear, conventional prefixes:

```text
feat: add token budget middleware
fix: correct circuit breaker state transition
docs: update provider contract
test: add PII masking edge cases
refactor: simplify retry classification
```

## Release Process

Maintainers should follow [RELEASE.md](RELEASE.md) before publishing a new
version. Pull requests that affect packaging, public APIs, or documentation
should mention whether the release checklist needs updates.
