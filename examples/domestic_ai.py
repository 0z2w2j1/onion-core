"""
Onion Core - 国内 AI 模型使用示例 (DeepSeek, 智谱, Kimi, 通义)

展示如何接入国内主流大模型，利用 Onion Core 的中间件能力进行治理。

运行：
    python examples/domestic_ai.py
"""

import asyncio
import os

from onion_core import AgentContext, Message, Pipeline
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    SafetyGuardrailMiddleware,
)
from onion_core.providers.domestic import DeepSeekProvider


async def main():
    # 1. 初始化国内 Provider
    # 这里以 DeepSeek 为例，你也可以换成 ZhipuAIProvider, MoonshotProvider 或 DashScopeProvider
    # 请确保设置了对应的环境变量
    api_key = os.getenv("DEEPSEEK_API_KEY", "your-api-key")
    
    # DeepSeek 提供了性价比极高的 V3/R1 模型，且完全兼容 OpenAI 协议
    provider = DeepSeekProvider(api_key=api_key, model="deepseek-chat")

    # 2. 构建 Pipeline
    async with Pipeline(
        provider=provider,
        max_retries=3,
        enable_circuit_breaker=True
    ) as pipeline:
        
        # 挂载治理能力
        pipeline.add_middleware(ObservabilityMiddleware())
        pipeline.add_middleware(SafetyGuardrailMiddleware())
        pipeline.add_middleware(ContextWindowMiddleware(max_tokens=4000))

        # 3. 构造请求
        ctx = AgentContext(messages=[
            Message(role="system", content="你是一个专业的 AI 助手。"),
            Message(role="user", content="请介绍一下你自己，并包含一个测试手机号 13800138000。")
        ])

        # 4. 执行
        print("--- 正在调用国内 AI 模型 ---")
        response = await pipeline.run(ctx)
        
        print(f"\n模型: {response.model}")
        print(f"响应内容: {response.content}")
        print(f"Token 消耗: {response.usage.total_tokens if response.usage else '未知'}")
        print(f"请求耗时: {ctx.metadata.get('duration_s', 0):.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
