# -*- coding: utf-8 -*-
"""
Onion Core - LM Studio 使用示例

展示如何接入 LM Studio 部署的本地大模型。

运行：
    python examples/lm_studio_example.py
"""

import asyncio
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers.local import LMStudioProvider
from onion_core.middlewares import (
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
    ObservabilityMiddleware
)

async def main():
    # 1. 初始化 LM Studio Provider
    # 请确保你已经启动了 LM Studio 并在 Local Server 选项卡中开启了服务器
    # 默认地址通常是 http://localhost:1234/v1
    provider = LMStudioProvider()

    # 2. 构建带治理能力的 Pipeline
    async with Pipeline(
        provider=provider,
        provider_timeout=60.0
    ) as pipeline:
        
        # 挂载中间件
        pipeline.add_middleware(ObservabilityMiddleware())
        pipeline.add_middleware(SafetyGuardrailMiddleware())
        pipeline.add_middleware(ContextWindowMiddleware(max_tokens=2000))

        # 3. 构造请求
        ctx = AgentContext(messages=[
            Message(role="user", content="你好，你觉得本地部署大模型有什么优势？")
        ])

        # 4. 执行
        print("--- 正在调用本地 LM Studio 模型 ---")
        try:
            response = await pipeline.run(ctx)
            print(f"\n模型响应: {response.content}")
            print(f"耗时统计: {ctx.metadata.get('duration_s', 0):.2f}s")
        except Exception as e:
            print(f"\n调用失败（请检查 LM Studio 服务器是否已开启）: {e}")

if __name__ == "__main__":
    asyncio.run(main())
