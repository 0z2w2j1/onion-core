# -*- coding: utf-8 -*-
"""
Onion Core - 熔断器实现
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .models import CircuitState, CircuitBreakerError

logger = logging.getLogger("onion_core.circuit_breaker")


class CircuitBreaker:
    """
    熔断器实现：防止对持续故障的 Provider 进行无效重试。

    状态机转换：
      - CLOSED -> OPEN: 连续失败次数超过 failure_threshold
      - OPEN -> HALF_OPEN: 经过 reset_timeout 秒后，允许少量请求测试恢复
      - HALF_OPEN -> CLOSED: HALF_OPEN 期间连续成功 success_threshold 次
      - HALF_OPEN -> OPEN: HALF_OPEN 期间出现 1 次失败
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """获取当前熔断器状态（含自动重置检查）。"""
        if self._state == CircuitState.OPEN and self._last_failure_time:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                # 实际更新内部状态，否则 record_success/record_failure 永远看不到 HALF_OPEN
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info("Circuit breaker '%s' entering HALF_OPEN state.", self.name)
        return self._state

    async def check_call(self) -> None:
        """调用前检查状态。若处于 OPEN 状态则抛出异常。"""
        async with self._lock:
            current_state = self.state  # 在锁内读取，确保状态转换原子性
            if current_state == CircuitState.OPEN:
                raise CircuitBreakerError(f"Circuit breaker '{self.name}' is OPEN.")

    async def record_success(self) -> None:
        """记录一次成功调用。"""
        async with self._lock:
            # 先触发可能的 OPEN→HALF_OPEN 转换
            _ = self.state
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._reset()
                    logger.info("Circuit breaker '%s' CLOSED (recovered).", self.name)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    async def record_failure(self) -> None:
        """记录一次失败调用。"""
        async with self._lock:
            self._last_failure_time = time.time()
            # 先触发可能的 OPEN→HALF_OPEN 转换，再判断当前状态
            _ = self.state
            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "Circuit breaker '%s' OPENED after %d failures.",
                        self.name, self._failure_count
                    )
            elif self._state == CircuitState.HALF_OPEN:
                # 半开状态下任何一次失败都直接重新切回 OPEN
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker '%s' returned to OPEN from HALF_OPEN.", self.name)

    def _reset(self) -> None:
        """内部重置计数。"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
