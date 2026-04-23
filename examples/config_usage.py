"""
Onion Core - 配置系统使用示例

展示三种配置来源：
  1. 代码直接构建
  2. JSON 配置文件
  3. 环境变量（ONION__ 前缀）

运行：
    python examples/config_usage.py
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

from onion_core import (
    AgentContext,
    ContextWindowConfig,
    EchoProvider,
    Message,
    ObservabilityConfig,
    OnionConfig,
    Pipeline,
    PipelineConfig,
    SafetyConfig,
)
from onion_core.observability.logging import configure_logging

configure_logging(level="INFO", json_format=False)


def demo_code_config() -> OnionConfig:
    print("\n=== 1. 代码直接构建 ===")
    cfg = OnionConfig(
        pipeline=PipelineConfig(max_retries=2, provider_timeout=30.0),
        safety=SafetyConfig(
            blocked_keywords=["ignore instructions", "system prompt"],
            blocked_tools=["exec_shell"],
        ),
        context_window=ContextWindowConfig(max_tokens=8000, keep_rounds=3),
        observability=ObservabilityConfig(log_level="DEBUG"),
    )
    print(f"  max_retries     = {cfg.pipeline.max_retries}")
    print(f"  provider_timeout= {cfg.pipeline.provider_timeout}")
    print(f"  max_tokens      = {cfg.context_window.max_tokens}")
    print(f"  blocked_keywords= {cfg.safety.blocked_keywords}")
    print(f"  get('context_window.max_tokens') = {cfg.get('context_window.max_tokens')}")
    return cfg


def demo_file_config() -> OnionConfig:
    print("\n=== 2. JSON 配置文件 ===")
    payload = {
        "pipeline": {"max_retries": 1, "provider_timeout": 20.0},
        "safety": {"blocked_keywords": ["forbidden"]},
        "context_window": {"max_tokens": 4000, "keep_rounds": 2},
        "observability": {"log_level": "INFO"},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(payload, f, indent=2)
        path = f.name

    try:
        cfg = OnionConfig.from_file(path)
        print(f"  Loaded from: {path}")
        print(f"  max_retries = {cfg.pipeline.max_retries}")
        print(f"  blocked_keywords = {cfg.safety.blocked_keywords}")
        return cfg
    finally:
        os.unlink(path)


def demo_env_config() -> OnionConfig:
    print("\n=== 3. 环境变量（ONION__ 前缀）===")
    os.environ["ONION__PIPELINE__MAX_RETRIES"] = "3"
    os.environ["ONION__PIPELINE__PROVIDER_TIMEOUT"] = "15.0"
    os.environ["ONION__CONTEXT_WINDOW__MAX_TOKENS"] = "2000"
    os.environ["ONION__SAFETY__ENABLE_PII_MASKING"] = "true"

    cfg = OnionConfig.from_env()
    print(f"  max_retries       = {cfg.pipeline.max_retries}")
    print(f"  provider_timeout  = {cfg.pipeline.provider_timeout}")
    print(f"  max_tokens        = {cfg.context_window.max_tokens}")
    print(f"  enable_pii_masking = {cfg.safety.enable_pii_masking}")

    for k in ["ONION__PIPELINE__MAX_RETRIES", "ONION__PIPELINE__PROVIDER_TIMEOUT",
              "ONION__CONTEXT_WINDOW__MAX_TOKENS", "ONION__SAFETY__ENABLE_PII_MASKING"]:
        os.environ.pop(k, None)

    return cfg


async def demo_pipeline_from_config(cfg: OnionConfig) -> None:
    print("\n=== 4. Pipeline.from_config ===")
    pipeline = Pipeline.from_config(
        provider=EchoProvider(reply="Hello from configured pipeline!"),
        config=cfg,
    )
    print(f"  Middlewares: {[mw.name for mw in pipeline.middlewares]}")

    ctx = AgentContext(messages=[
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello!"),
    ])
    response = await pipeline.run(ctx)
    print(f"  Response: {response.content}")
    print(f"  Duration: {ctx.metadata.get('duration_s', 'N/A'):.4f}s")


async def main() -> None:
    cfg_code = demo_code_config()
    demo_file_config()
    demo_env_config()
    await demo_pipeline_from_config(cfg_code)


if __name__ == "__main__":
    asyncio.run(main())
