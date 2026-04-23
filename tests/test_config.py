"""OnionConfig 和 Pipeline.from_config 测试。"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from onion_core import (
    AgentContext,
    ContextWindowConfig,
    EchoProvider,
    LLMResponse,
    Message,
    ObservabilityConfig,
    Pipeline,
    PipelineConfig,
    SafetyConfig,
    OnionConfig,
)
from onion_core.middlewares.safety import SecurityException

from .conftest import make_context


# ── OnionConfig 基础 ───────────────────────────────────────────────────────

def test_onion_config_defaults():
    cfg = OnionConfig()
    assert cfg.pipeline.max_retries == 0
    assert cfg.pipeline.provider_timeout is None
    assert cfg.safety.enable_pii_masking is True
    assert cfg.context_window.max_tokens == 4000
    assert cfg.observability.log_level == "INFO"


def test_onion_config_code_construction():
    cfg = OnionConfig(
        pipeline=PipelineConfig(max_retries=3, provider_timeout=10.0),
        safety=SafetyConfig(blocked_keywords=["bad word"]),
        context_window=ContextWindowConfig(max_tokens=8000, keep_rounds=4),
    )
    assert cfg.pipeline.max_retries == 3
    assert cfg.pipeline.provider_timeout == 10.0
    assert "bad word" in cfg.safety.blocked_keywords
    assert cfg.context_window.max_tokens == 8000


def test_onion_config_get_dotpath():
    cfg = OnionConfig(context_window=ContextWindowConfig(max_tokens=2048))
    assert cfg.get("context_window.max_tokens") == 2048
    assert cfg.get("pipeline.max_retries") == 0
    assert cfg.get("nonexistent.key", "default") == "default"


def test_onion_config_to_context_config():
    cfg = OnionConfig()
    data = cfg.to_context_config()
    assert "onion" in data
    assert "pipeline" in data["onion"]


# ── from_file（JSON）─────────────────────────────────────────────────────────

def test_onion_config_from_json_file():
    payload = {
        "pipeline": {"max_retries": 2, "provider_timeout": 20.0},
        "safety": {"blocked_keywords": ["forbidden"]},
        "context_window": {"max_tokens": 6000},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        path = f.name

    try:
        cfg = OnionConfig.from_file(path)
        assert cfg.pipeline.max_retries == 2
        assert cfg.pipeline.provider_timeout == 20.0
        assert "forbidden" in cfg.safety.blocked_keywords
        assert cfg.context_window.max_tokens == 6000
    finally:
        os.unlink(path)


def test_onion_config_from_file_not_found():
    with pytest.raises(FileNotFoundError):
        OnionConfig.from_file("/nonexistent/path/config.json")


def test_onion_config_from_file_unsupported_format():
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        f.write(b"[pipeline]\nmax_retries = 1\n")
        path = f.name
    try:
        with pytest.raises(ValueError, match="Unsupported"):
            OnionConfig.from_file(path)
    finally:
        os.unlink(path)


# ── from_env ──────────────────────────────────────────────────────────────────

def test_onion_config_from_env(monkeypatch):
    monkeypatch.setenv("ONION__PIPELINE__MAX_RETRIES", "5")
    monkeypatch.setenv("ONION__PIPELINE__PROVIDER_TIMEOUT", "15.0")
    monkeypatch.setenv("ONION__CONTEXT_WINDOW__MAX_TOKENS", "2000")
    monkeypatch.setenv("ONION__SAFETY__ENABLE_PII_MASKING", "false")

    cfg = OnionConfig.from_env()
    assert cfg.pipeline.max_retries == 5
    assert cfg.pipeline.provider_timeout == 15.0
    assert cfg.context_window.max_tokens == 2000
    assert cfg.safety.enable_pii_masking is False


def test_onion_config_from_env_invalid_value_ignored(monkeypatch):
    """pydantic-settings 会对无效环境变量值抛出 ValidationError（严格的类型校验是预期行为）。"""
    from pydantic import ValidationError
    monkeypatch.setenv("ONION__PIPELINE__MAX_RETRIES", "not_a_number")
    monkeypatch.setenv("ONION__PIPELINE__PROVIDER_TIMEOUT", "5.0")
    with pytest.raises(ValidationError):
        OnionConfig.from_env()


# ── Pipeline.from_config ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_from_config_basic():
    """from_config 应构建包含三个内置中间件的 Pipeline。"""
    cfg = OnionConfig()
    p = Pipeline.from_config(provider=EchoProvider(), config=cfg)

    assert len(p.middlewares) == 3
    names = [mw.name for mw in p.middlewares]
    assert "ObservabilityMiddleware" in names
    assert "SafetyGuardrailMiddleware" in names
    assert "ContextWindowMiddleware" in names


@pytest.mark.asyncio
async def test_pipeline_from_config_runs():
    cfg = OnionConfig()
    p = Pipeline.from_config(provider=EchoProvider(reply="cfg-reply"), config=cfg)
    ctx = make_context()
    resp = await p.run(ctx)
    assert isinstance(resp, LLMResponse)
    assert resp.content == "cfg-reply"


@pytest.mark.asyncio
async def test_pipeline_from_config_safety_keywords():
    """from_config 传入的 blocked_keywords 应生效。"""
    cfg = OnionConfig(
        safety=SafetyConfig(blocked_keywords=["forbidden phrase"])
    )
    p = Pipeline.from_config(provider=EchoProvider(), config=cfg)
    ctx = AgentContext(messages=[Message(role="user", content="this is a forbidden phrase")])
    with pytest.raises(SecurityException):
        await p.run(ctx)


@pytest.mark.asyncio
async def test_pipeline_from_config_context_window():
    """from_config 传入的 max_tokens 应被 ContextWindowMiddleware 使用。"""
    from tests.conftest import make_long_context

    cfg = OnionConfig(context_window=ContextWindowConfig(max_tokens=500, keep_rounds=1))
    p = Pipeline.from_config(provider=EchoProvider(), config=cfg)
    ctx = make_long_context(n_rounds=20, words_per_msg=100)
    await p.run(ctx)
    assert ctx.metadata["context_truncated"] is True


@pytest.mark.asyncio
async def test_pipeline_from_config_pipeline_params():
    """from_config 应将 PipelineConfig 参数传给 Pipeline。"""
    cfg = OnionConfig(
        pipeline=PipelineConfig(max_retries=2, provider_timeout=5.0)
    )
    p = Pipeline.from_config(provider=EchoProvider(), config=cfg)
    assert p._max_retries == 2
    assert p._provider_timeout == 5.0
