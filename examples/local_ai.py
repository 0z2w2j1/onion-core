"""
Onion Core - 本地 AI 使用示例 (Ollama / vLLM)

展示如何接入本地部署的大模型，并利用 Onion Core 进行安全审计和流量治理。

运行：
    python examples/local_ai.py
"""

import asyncio

from onion_core import AgentContext, Message, Pipeline
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    SafetyGuardrailMiddleware,
)
from onion_core.providers.local import OllamaProvider


async def main():
    # 1. 初始化本地 Provider (以 Ollama 为例)
    # 请确保你已经安装并启动了 Ollama，并拉取了模型：ollama run llama3
    provider = OllamaProvider(model="llama3")

    # 2. 构建带治理能力的 Pipeline
    async with Pipeline(
        provider=provider,
        provider_timeout=60.0  # 本地运行可能较慢，适当调大超时时间
    ) as pipeline:
        
        # 挂载中间件
        pipeline.add_middleware(ObservabilityMiddleware())
        pipeline.add_middleware(SafetyGuardrailMiddleware())
        pipeline.add_middleware(ContextWindowMiddleware(max_tokens=2000))

        # 3. 构造请求
        ctx = AgentContext(messages=[
            Message(role="user", content="你好，请用一句话介绍你自己。")
        ])

        # 4. 执行并观察中间件效果
        print("--- 正在调用本地 Ollama 模型 ---")
        try:
            response = await pipeline.run(ctx)
            print(f"\n模型响应: {response.content}")
            print(f"耗时统计: {ctx.metadata.get('duration_s', 0):.2f}s")
        except Exception as e:
            print(f"\n调用失败（请检查 Ollama 是否启动）: {e}")

if __name__ == "__main__":
    asyncio.run(main())
