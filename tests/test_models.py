"""Core model validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from onion_core import LLMResponse, Message, ToolCall, UsageStats


@pytest.mark.parametrize("role", ["system", "user", "assistant", "tool"])
def test_message_valid_roles(role: str):
    msg = Message(role=role, content="test")
    assert msg.role == role


def test_message_invalid_role():
    with pytest.raises(ValidationError):
        Message(role="banana", content="test")


def test_llm_response_properties():
    resp = LLMResponse(
        content="hi",
        finish_reason="stop",
        usage=UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        tool_calls=[ToolCall(id="t1", name="search", arguments={})],
    )
    assert resp.is_complete
    assert resp.has_tool_calls
    assert resp.usage.total_tokens == 15
