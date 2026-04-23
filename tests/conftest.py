"""共享 fixtures，所有测试文件自动加载。"""

from __future__ import annotations

import pytest
import pytest_asyncio

from onion_core import (
    AgentContext,
    EchoProvider,
    Message,
    Pipeline,
)
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    SafetyGuardrailMiddleware,
)


# ── 基础 fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def echo_provider():
    return EchoProvider(reply="Hello from echo.")


@pytest.fixture
def simple_context():
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


@pytest.fixture
def pipeline(echo_provider):
    return (
        Pipeline(provider=echo_provider)
        .add_middleware(ObservabilityMiddleware())
        .add_middleware(SafetyGuardrailMiddleware())
        .add_middleware(ContextWindowMiddleware(max_tokens=4000))
    )


@pytest_asyncio.fixture
async def started_pipeline(pipeline):
    async with pipeline:
        yield pipeline


def make_context():
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
        ]
    )


def make_long_context(n_rounds: int = 20, words_per_msg: int = 200):
    """生成超长上下文，用于测试 Token 裁剪。"""
    messages = [
        Message(role="system", content="You are a helpful assistant. If the conversation gets too long, older messages may be summarized."),
    ]
    for i in range(n_rounds):
        messages.append(Message(role="user", content=f"Round {i}: " + "word " * words_per_msg))
        messages.append(Message(role="assistant", content="That is a long message. " * words_per_msg))
    messages.append(Message(role="user", content="Final question?"))
    return AgentContext(messages=messages)
