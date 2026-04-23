"""
Onion Core - 熔断器测试
"""

from __future__ import annotations

import asyncio

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline
from onion_core.models import CircuitBreakerError


class FlakyProvider(EchoProvider):
    def __init__(self, fail_count: int = 5):
        super().__init__(reply=None)
        self.fail_count = fail_count
        self.current_calls = 0

    async def complete(self, context: AgentContext) -> LLMResponse:
        self.current_calls += 1
        if self.current_calls <= self.fail_count:
            raise ConnectionError("Service Unavailable")
        return await super().complete(context)


@pytest.mark.asyncio
async def test_circuit_breaker_trips():
    """测试熔断器触发逻辑：连续失败后进入 OPEN 状态。"""
    fail_threshold = 3
    provider = FlakyProvider(fail_count=10)
    
    # 启用熔断，阈值为 3
    p = Pipeline(
        provider=provider,
        enable_circuit_breaker=True,
        circuit_failure_threshold=fail_threshold,
        max_retries=0  # 关闭重试，方便观察单次调用
    )
    
    ctx = AgentContext(messages=[Message(role="user", content="hi")])
    
    # 前 3 次调用应该抛出 ConnectionError
    for _ in range(fail_threshold):
        with pytest.raises(ConnectionError):
            await p.run(ctx)
            
    # 第 4 次调用应该直接被熔断器拦截，抛出 CircuitBreakerError
    with pytest.raises(CircuitBreakerError):
        await p.run(ctx)
    
    # 验证 Provider 并没有被调用第 4 次
    assert provider.current_calls == fail_threshold


@pytest.mark.asyncio
async def test_circuit_breaker_recovery():
    """测试熔断器恢复逻辑：经过冷却时间后进入 HALF_OPEN 并尝试恢复。"""
    fail_threshold = 2
    recovery_timeout = 0.5
    provider = FlakyProvider(fail_count=2) # 前 2 次失败
    
    p = Pipeline(
        provider=provider,
        enable_circuit_breaker=True,
        circuit_failure_threshold=fail_threshold,
        circuit_recovery_timeout=recovery_timeout,
        max_retries=0
    )
    
    ctx = AgentContext(messages=[Message(role="user", content="hi")])
    
    # 触发熔断
    for _ in range(fail_threshold):
        with pytest.raises(ConnectionError):
            await p.run(ctx)
            
    # 确认已熔断
    with pytest.raises(CircuitBreakerError):
        await p.run(ctx)
        
    # 等待恢复时间
    await asyncio.sleep(recovery_timeout + 0.1)
    
    # 此时应处于 HALF_OPEN，Provider 已设置前 2 次失败，现在应成功
    resp = await p.run(ctx)
    assert resp.content == "Echo: hi"
    
    # 验证连续成功后回到 CLOSED
    # 默认成功阈值是 2
    resp2 = await p.run(ctx)
    assert resp2.content == "Echo: hi"


@pytest.mark.asyncio
async def test_circuit_breaker_fallback():
    """测试熔断器与 Fallback 的集成：主 Provider 熔断后应自动尝试备用 Provider。"""
    primary = FlakyProvider(fail_count=5)
    backup = EchoProvider(reply="Backup response")
    
    p = Pipeline(
        provider=primary,
        fallback_providers=[backup],
        enable_circuit_breaker=True,
        circuit_failure_threshold=2,
        max_retries=0
    )
    
    ctx = AgentContext(messages=[Message(role="user", content="hi")])
    
    # 前 2 次：primary 报错，触发 fallback 到 backup
    for _ in range(2):
        resp = await p.run(ctx)
        assert resp.content == "Backup response"
        
    # 第 3 次：primary 已熔断，直接跳过并调用 backup
    # 此时 primary 不应有第 3 次调用
    resp = await p.run(ctx)
    assert resp.content == "Backup response"
    assert primary.current_calls == 2
