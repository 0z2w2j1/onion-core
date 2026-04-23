"""
Onion Core 同步 API 使用示例

演示如何在非异步环境（如 Flask/Django/脚本）中使用同步 API。
"""

from onion_core import AgentContext, EchoProvider, Message, Pipeline
from onion_core.middlewares import (
    ContextWindowMiddleware,
    ObservabilityMiddleware,
    SafetyGuardrailMiddleware,
)


def example_basic_sync():
    """基础同步调用示例。"""
    print("=== 基础同步调用 ===")

    with Pipeline(provider=EchoProvider()) as p:
        ctx = AgentContext(
            messages=[Message(role="user", content="Hello, world!")]
        )
        response = p.run_sync(ctx)
        print(f"Response: {response.content}")
        print()


def example_streaming_sync():
    """同步流式调用示例。"""
    print("=== 同步流式调用 ===")

    with Pipeline(provider=EchoProvider()) as p:
        ctx = AgentContext(
            messages=[Message(role="user", content="Tell me a story")]
        )
        print("Streaming response: ", end="", flush=True)
        for chunk in p.stream_sync(ctx):
            if chunk.delta:
                print(chunk.delta, end="", flush=True)
        print("\n")


def example_with_middlewares():
    """带中间件的同步调用示例。"""
    print("=== 带中间件的同步调用 ===")

    with Pipeline(provider=EchoProvider()) as p:
        # 添加中间件
        p.add_middleware(ObservabilityMiddleware())
        p.add_middleware(SafetyGuardrailMiddleware())
        p.add_middleware(ContextWindowMiddleware(max_tokens=2000))

        # PII 脱敏测试
        ctx = AgentContext(
            messages=[
                Message(
                    role="user",
                    content="My phone number is 13812345678 and email is test@example.com",
                )
            ]
        )

        response = p.run_sync(ctx)
        print("Original: My phone number is 13812345678 and email is test@example.com")
        print(f"Masked:   {response.content}")
        print()


def example_manual_lifecycle():
    """手动管理生命周期的示例。"""
    print("=== 手动生命周期管理 ===")

    p = Pipeline(provider=EchoProvider())
    try:
        p.startup_sync()

        ctx = AgentContext(
            messages=[Message(role="user", content="Manual lifecycle test")]
        )
        response = p.run_sync(ctx)
        print(f"Response: {response.content}")
    finally:
        p.shutdown_sync()
    print()


def example_tool_calls_sync():
    """同步工具调用示例。"""
    print("=== 同步工具调用 ===")

    from onion_core import ToolCall, ToolResult

    with Pipeline(provider=EchoProvider()) as p:
        ctx = AgentContext(messages=[])

        # 执行工具调用
        tool_call = ToolCall(
            id="call-1", name="get_weather", arguments={"city": "Beijing"}
        )
        intercepted = p.execute_tool_call_sync(ctx, tool_call)
        print(f"Intercepted tool call: {intercepted.name}")

        # 处理工具结果
        tool_result = ToolResult(
            tool_call_id="call-1",
            name="get_weather",
            result="Sunny, 25°C",
        )
        processed = p.execute_tool_result_sync(ctx, tool_result)
        print(f"Processed result: {processed.result}")
    print()


if __name__ == "__main__":
    example_basic_sync()
    example_streaming_sync()
    example_with_middlewares()
    example_manual_lifecycle()
    example_tool_calls_sync()

    print("✅ 所有同步 API 示例执行完成！")
