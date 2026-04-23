"""PII 规则精确性测试（3.6 补充）。"""

from __future__ import annotations

import re

import pytest

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import SafetyGuardrailMiddleware
from onion_core.middlewares.safety import PiiRule, BUILTIN_PII_RULES


def mask(text: str, rules=None) -> str:
    mw = SafetyGuardrailMiddleware(enable_builtin_pii=(rules is None))
    if rules:
        for r in rules:
            mw.add_pii_rule(r)
    return mw._mask_pii(text)


# ── 邮箱 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected_masked", [
    ("contact user@example.com please", True),
    ("admin@corp.co.uk is the address", True),
    ("no email here", False),
    ("not-an-email@", False),          # 缺少 TLD
])
def test_email_masking(text, expected_masked):
    result = mask(text)
    if expected_masked:
        assert "user@" not in result and "admin@" not in result
        assert "[email]" in result
    else:
        assert "[email]" not in result


# ── 中国手机号 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,should_mask", [
    ("call 13812345678 now", True),
    ("call 19912345678 now", True),
    ("number 12345678901 here", False),   # 不以 1[3-9] 开头
    ("id 110101199001011234 here", False), # 身份证，不是手机号（由 id_card 规则处理）
    ("price is 13800000000 yuan", True),  # 符合手机号格式
])
def test_phone_cn_masking(text, should_mask):
    result = mask(text)
    if should_mask:
        assert "***" in result
    else:
        # 手机号规则不应误触发
        phone_rule = next(r for r in BUILTIN_PII_RULES if r.name == "phone_cn")
        assert not phone_rule.pattern.search(text) or should_mask


# ── 国际电话（改进后的精确正则）────────────────────────────────────────────────

@pytest.mark.parametrize("text,should_mask", [
    ("+1-555-123-4567 is the number", True),
    ("+44 20 7946 0958 call us", True),
    ("plain text without phone", False),
    ("version 1.2.3 released", False),   # 版本号不应被误匹配
    ("price $12.50 today", False),       # 价格不应被误匹配
])
def test_phone_intl_masking(text, should_mask):
    result = mask(text)
    intl_rule = next(r for r in BUILTIN_PII_RULES if r.name == "phone_intl")
    matched = bool(intl_rule.pattern.search(text))
    assert matched == should_mask


# ── 身份证号 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,should_mask", [
    ("ID: 110101199001011234", True),
    ("ID: 11010119900101123X", True),    # X 结尾
    ("short 1234567890123456", False),   # 16 位，不足 18 位
    ("too long 1101011990010112345", False),  # 19 位
])
def test_id_card_masking(text, should_mask):
    result = mask(text)
    if should_mask:
        assert "[ID]" in result
    else:
        assert "[ID]" not in result


# ── 自定义规则 ────────────────────────────────────────────────────────────────

def test_custom_pii_rule():
    rule = PiiRule(
        name="api_key",
        pattern=re.compile(r"sk-[a-zA-Z0-9]{8,}"),
        replacement="[API_KEY]",
    )
    result = mask("Use key sk-abcdef1234567890 to authenticate", rules=[rule])
    assert "sk-abcdef1234567890" not in result
    assert "[API_KEY]" in result


def test_custom_rule_no_false_positive():
    rule = PiiRule(
        name="api_key",
        pattern=re.compile(r"sk-[a-zA-Z0-9]{8,}"),
        replacement="[API_KEY]",
    )
    result = mask("no api key here, just text", rules=[rule])
    assert "[API_KEY]" not in result
    assert result == "no api key here, just text"


def test_multiple_pii_in_one_text():
    text = "Email user@test.com or call 13812345678"
    result = mask(text)
    assert "user@test.com" not in result
    assert "13812345678" not in result
    assert "[email]" in result
    assert "***" in result


# ── 流式 PII 过滤 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_pii_masking():
    """流式输出中的 PII 应在 finish_reason 时被整体过滤。"""
    p = Pipeline(
        provider=EchoProvider(reply="Phone: 13812345678")
    ).add_middleware(SafetyGuardrailMiddleware())

    ctx = AgentContext(messages=[Message(role="user", content="phone")])
    chunks = []
    async for c in p.stream(ctx):
        chunks.append(c.delta)
    full = "".join(chunks)
    assert "13812345678" not in full
    assert "***" in full


@pytest.mark.asyncio
async def test_stream_buffer_cleaned_on_error():
    """流中途出错时，PII 缓冲区应被清理。"""
    from onion_core.provider import LLMProvider
    from onion_core.models import StreamChunk

    class ErrorProvider(LLMProvider):
        async def complete(self, ctx): ...
        async def stream(self, ctx):
            yield StreamChunk(delta="Phone: 138", index=0)
            raise RuntimeError("stream error")

    p = Pipeline(provider=ErrorProvider()).add_middleware(SafetyGuardrailMiddleware())
    ctx = AgentContext(messages=[Message(role="user", content="test")])

    with pytest.raises(RuntimeError):
        async for _ in p.stream(ctx):
            pass

    buf_key = f"_safety_buf_{ctx.request_id}"
    assert buf_key not in ctx.metadata


# ── 配置系统 ─────────────────────────────────────────────────────────────────

def test_config_code_construction():
    from onion_core import OnionConfig, ContextWindowConfig, SafetyConfig
    cfg = OnionConfig(
        context_window=ContextWindowConfig(max_tokens=8000, keep_rounds=4),
        safety=SafetyConfig(enable_pii_masking=False),
    )
    assert cfg.get("context_window.max_tokens") == 8000
    assert cfg.get("context_window.keep_rounds") == 4
    assert cfg.get("safety.enable_pii_masking") is False
    assert cfg.get("nonexistent.key", "fallback") == "fallback"


def test_config_env(monkeypatch):
    from onion_core import OnionConfig
    monkeypatch.setenv("ONION__CONTEXT_WINDOW__MAX_TOKENS", "6000")
    monkeypatch.setenv("ONION__PIPELINE__MAX_RETRIES", "3")
    cfg = OnionConfig.from_env()
    assert cfg.context_window.max_tokens == 6000
    assert cfg.pipeline.max_retries == 3


def test_config_env_invalid_value_ignored(monkeypatch):
    """pydantic-settings 会对无效环境变量值抛出 ValidationError（严格的类型校验是预期行为）。"""
    from pydantic import ValidationError
    from onion_core import OnionConfig
    monkeypatch.setenv("ONION__CONTEXT_WINDOW__MAX_TOKENS", "not_a_number")
    with pytest.raises(ValidationError):
        OnionConfig.from_env()


def test_config_json_file(tmp_path):
    import json
    from onion_core import OnionConfig
    cfg_data = {
        "context_window": {"max_tokens": 2000, "keep_rounds": 1},
        "safety": {"blocked_keywords": ["test_keyword"]},
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg_data))
    cfg = OnionConfig.from_file(p)
    assert cfg.context_window.max_tokens == 2000
    assert "test_keyword" in cfg.safety.blocked_keywords


def test_config_file_not_found():
    from onion_core import OnionConfig
    with pytest.raises(FileNotFoundError):
        OnionConfig.from_file("/nonexistent/path/config.json")


# ── 模型校验 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["system", "user", "assistant", "tool"])
def test_message_valid_roles(role):
    from onion_core import Message
    msg = Message(role=role, content="test")
    assert msg.role == role


def test_message_invalid_role():
    from pydantic import ValidationError
    from onion_core import Message
    with pytest.raises(ValidationError):
        Message(role="banana", content="test")


def test_llm_response_properties():
    from onion_core import LLMResponse, ToolCall, UsageStats
    resp = LLMResponse(
        content="hi",
        finish_reason="stop",
        usage=UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        tool_calls=[ToolCall(id="t1", name="search", arguments={})],
    )
    assert resp.is_complete
    assert resp.has_tool_calls
    assert resp.usage.total_tokens == 15
