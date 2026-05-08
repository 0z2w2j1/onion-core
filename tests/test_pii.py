"""PII masking and streaming safety tests."""

from __future__ import annotations

import re

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline, StreamChunk
from onion_core.middlewares import SafetyGuardrailMiddleware
from onion_core.middlewares.safety import BUILTIN_PII_RULES, PiiRule
from onion_core.provider import LLMProvider


def mask(text: str, rules: list[PiiRule] | None = None) -> str:
    mw = SafetyGuardrailMiddleware(enable_builtin_pii=(rules is None))
    if rules:
        for rule in rules:
            mw.add_pii_rule(rule)
    return mw._mask_pii(text)


@pytest.mark.parametrize(
    ("text", "expected_masked"),
    [
        ("contact user@example.com please", True),
        ("admin@corp.co.uk is the address", True),
        ("no email here", False),
        ("not-an-email@", False),
    ],
)
def test_email_masking(text: str, expected_masked: bool):
    result = mask(text)
    if expected_masked:
        assert "user@" not in result and "admin@" not in result
        assert "[email]" in result
    else:
        assert "[email]" not in result


@pytest.mark.parametrize(
    ("text", "should_mask"),
    [
        ("call 13812345678 now", True),
        ("call 19912345678 now", True),
        ("number 12345678901 here", False),
        ("id 110101199001011234 here", False),
        ("price is 13800000000 yuan", True),
    ],
)
def test_phone_cn_masking(text: str, should_mask: bool):
    result = mask(text)
    if should_mask:
        assert "***" in result
    else:
        phone_rule = next(rule for rule in BUILTIN_PII_RULES if rule.name == "phone_cn")
        assert not phone_rule.pattern.search(text)


@pytest.mark.parametrize(
    ("text", "should_mask"),
    [
        ("+1-555-123-4567 is the number", True),
        ("+44 20 7946 0958 call us", True),
        ("plain text without phone", False),
        ("version 1.2.3 released", False),
        ("price $12.50 today", False),
    ],
)
def test_phone_intl_masking(text: str, should_mask: bool):
    intl_rule = next(rule for rule in BUILTIN_PII_RULES if rule.name == "phone_intl")
    assert bool(intl_rule.pattern.search(text)) == should_mask


@pytest.mark.parametrize(
    ("text", "should_mask"),
    [
        ("ID: 110101199001011234", True),
        ("ID: 11010119900101123X", True),
        ("short 1234567890123456", False),
        ("too long 1101011990010112345", False),
    ],
)
def test_id_card_masking(text: str, should_mask: bool):
    result = mask(text)
    if should_mask:
        assert "[ID]" in result
    else:
        assert "[ID]" not in result


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
    result = mask("Email user@test.com or call 13812345678")
    assert "user@test.com" not in result
    assert "13812345678" not in result
    assert "[email]" in result
    assert "***" in result


@pytest.mark.asyncio
async def test_stream_pii_masking():
    p = Pipeline(provider=EchoProvider(reply="Phone: 13812345678")).add_middleware(
        SafetyGuardrailMiddleware()
    )

    ctx = AgentContext(messages=[Message(role="user", content="phone")])
    chunks = []
    async for chunk in p.stream(ctx):
        chunks.append(chunk.delta)
    full = "".join(chunks)
    assert "13812345678" not in full
    assert "***" in full


@pytest.mark.asyncio
async def test_stream_buffer_cleaned_on_error():
    class ErrorProvider(LLMProvider):
        async def complete(self, context: AgentContext) -> LLMResponse:
            raise NotImplementedError

        async def stream(self, context: AgentContext):
            yield StreamChunk(delta="Phone: 138", index=0)
            raise RuntimeError("stream error")

    p = Pipeline(provider=ErrorProvider()).add_middleware(SafetyGuardrailMiddleware())
    ctx = AgentContext(messages=[Message(role="user", content="test")])

    with pytest.raises(RuntimeError):
        async for _ in p.stream(ctx):
            pass

    assert f"_safety_buf_{ctx.request_id}" not in ctx.metadata
