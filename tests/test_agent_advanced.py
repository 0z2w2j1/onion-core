"""AgentLoop 完整功能测试。"""

from __future__ import annotations

import pytest

from onion_core import AgentContext, EchoProvider, LLMResponse, Message, Pipeline
from onion_core.agent import AgentLoop, AgentLoopError
from onion_core.models import FinishReason, ToolCall
from onion_core.tools import ToolRegistry


def make_context():
    """创建测试上下文。"""
    return AgentContext(
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="What's the weather?"),
        ]
    )


class MockToolProvider(EchoProvider):
    """模拟返回工具调用的 Provider。"""

    def __init__(self, tool_calls: list[ToolCall] | None = None, final_reply: str = "Done"):
        super().__init__(reply=final_reply)
        self._tool_calls = tool_calls or []
        self._call_count = 0

    async def complete(self, context: AgentContext) -> LLMResponse:
        self._call_count += 1
        
        # 第一次调用返回工具调用
        if self._call_count == 1 and self._tool_calls:
            return LLMResponse(
                content=None,
                tool_calls=self._tool_calls,
                finish_reason=FinishReason.TOOL_CALLS,
                model="mock-1.0",
            )
        
        # 后续调用返回最终回复
        return await super().complete(context)


class TestAgentLoopBasic:
    """测试 AgentLoop 基本功能。"""

    @pytest.mark.asyncio
    async def test_agent_loop_no_tools_returns_immediately(self):
        """无工具调用时立即返回。"""
        provider = EchoProvider(reply="Hello")
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content == "Hello"
        assert response.finish_reason == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_agent_loop_single_tool_call(self):
        """单轮工具调用。"""
        tool_call = ToolCall(
            id="call_1",
            name="get_weather",
            arguments={"city": "Beijing"},
        )
        
        provider = MockToolProvider(tool_calls=[tool_call], final_reply="Weather is sunny")
        registry = ToolRegistry()
        
        @registry.register
        async def get_weather(city: str) -> str:
            """Get weather for a city."""
            return f"Weather in {city}: Sunny"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content == "Weather is sunny"
        assert provider._call_count == 2  # 1次工具调用 + 1次最终回复

    @pytest.mark.asyncio
    async def test_agent_loop_multiple_tool_calls(self):
        """多工具调用并行执行。"""
        tool_calls = [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Beijing"}),
            ToolCall(id="call_2", name="get_time", arguments={"timezone": "UTC"}),
        ]
        
        provider = MockToolProvider(tool_calls=tool_calls, final_reply="All done")
        registry = ToolRegistry()
        
        @registry.register
        async def get_weather(city: str) -> str:
            return "Weather: Sunny"
        
        @registry.register
        async def get_time(timezone: str) -> str:
            return "Time: 12:00"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content == "All done"
        assert provider._call_count == 2

    @pytest.mark.asyncio
    async def test_agent_loop_multi_turn_conversation(self):
        """多轮对话（工具调用后继续对话）。"""
        call_sequence = []
        
        class MultiTurnProvider(EchoProvider):
            async def complete(self, context: AgentContext) -> LLMResponse:
                call_sequence.append(len(context.messages))
                
                # 第1次：返回工具调用
                if len(call_sequence) == 1:
                    return LLMResponse(
                        content=None,
                        tool_calls=[ToolCall(id="call_1", name="search", arguments={"query": "test"})],
                        finish_reason=FinishReason.TOOL_CALLS,
                    )
                
                # 第2次：返回最终回复
                return await super().complete(context)
        
        provider = MultiTurnProvider()
        registry = ToolRegistry()
        
        @registry.register
        async def search(query: str) -> str:
            return f"Search result for: {query}"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content
        assert len(call_sequence) == 2
        # 验证消息历史正确追加（至少完成了调用）


class TestAgentLoopErrorHandling:
    """测试 AgentLoop 错误处理。"""

    @pytest.mark.asyncio
    async def test_agent_loop_unknown_tool_returns_error_result(self):
        """未知工具返回错误结果。"""
        tool_call = ToolCall(
            id="call_1",
            name="unknown_tool",
            arguments={},
        )
        
        provider = MockToolProvider(tool_calls=[tool_call], final_reply="Completed with errors")
        registry = ToolRegistry()
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        ctx = make_context()
        async with pipeline:
            response = await loop.run(ctx)

        assert response.content == "Completed with errors"
        assert any(
            msg.role == "tool" and "Error" in str(msg.content)
            for msg in ctx.messages
        )

    @pytest.mark.asyncio
    async def test_agent_loop_tool_execution_error(self):
        """工具执行失败时的错误处理。"""
        tool_call = ToolCall(
            id="call_1",
            name="failing_tool",
            arguments={},
        )
        
        provider = MockToolProvider(tool_calls=[tool_call], final_reply="Done")
        registry = ToolRegistry()
        
        @registry.register
        async def failing_tool() -> str:
            raise RuntimeError("Tool execution failed")
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content == "Done"

    @pytest.mark.asyncio
    async def test_agent_loop_max_turns_no_raise(self):
        """达到最大轮数时不抛出异常（默认行为）。"""
        class AlwaysToolCallsProvider(EchoProvider):
            async def complete(self, context: AgentContext) -> LLMResponse:
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(id="call_1", name="test", arguments={})],
                    finish_reason=FinishReason.TOOL_CALLS,
                )
        
        provider = AlwaysToolCallsProvider()
        registry = ToolRegistry()
        
        @registry.register
        async def test_tool() -> str:
            return "result"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry, max_turns=3, raise_on_max_turns=False)

        async with pipeline:
            response = await loop.run(make_context())

        # 应返回最后一次响应，不抛出异常
        assert response is not None

    @pytest.mark.asyncio
    async def test_agent_loop_max_turns_raises(self):
        """达到最大轮数时抛出异常。"""
        class AlwaysToolCallsProvider(EchoProvider):
            async def complete(self, context: AgentContext) -> LLMResponse:
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(id="call_1", name="test_tool", arguments={})],
                    finish_reason=FinishReason.TOOL_CALLS,
                )
        
        provider = AlwaysToolCallsProvider()
        registry = ToolRegistry()
        
        @registry.register
        async def test_tool() -> str:
            return "result"
        
        # Disable progress detection to allow max_turns to be reached
        context = AgentContext(
            messages=[
                Message(role="system", content="You are a helpful assistant."),
                Message(role="user", content="What's the weather?"),
            ],
            config={"agent_progress_window": 0},
        )
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry, max_turns=3, raise_on_max_turns=True)

        async with pipeline:
            with pytest.raises(AgentLoopError, match="exceeded max_turns"):
                await loop.run(context)


class TestAgentLoopMiddlewareIntegration:
    """测试 AgentLoop 与中间件集成。"""

    @pytest.mark.asyncio
    async def test_agent_loop_pipeline_middleware_applied(self):
        """验证中间件在 AgentLoop 中被正确应用。"""
        middleware_calls = []
        
        from onion_core.base import BaseMiddleware
        
        class TrackingMW(BaseMiddleware):
            async def process_request(self, context: AgentContext) -> AgentContext:
                middleware_calls.append("request")
                return context
            
            async def process_response(self, context: AgentContext, response: LLMResponse) -> LLMResponse:
                middleware_calls.append("response")
                return response
            
            async def process_stream_chunk(self, ctx, c):
                return c
            
            async def on_tool_call(self, context: AgentContext, tool_call: ToolCall) -> ToolCall:
                middleware_calls.append(f"tool_call:{tool_call.name}")
                return tool_call
            
            async def on_tool_result(self, context: AgentContext, result) -> object:
                middleware_calls.append(f"tool_result:{result.name}")
                return result
            
            async def on_error(self, ctx, e):
                pass
        
        tool_call = ToolCall(id="call_1", name="test_tool", arguments={})
        provider = MockToolProvider(tool_calls=[tool_call], final_reply="Done")
        
        registry = ToolRegistry()
        
        @registry.register
        async def test_tool() -> str:
            return "result"
        
        pipeline = Pipeline(provider=provider).add_middleware(TrackingMW())
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            await loop.run(make_context())

        # 验证中间件被调用
        assert "request" in middleware_calls
        assert "response" in middleware_calls
        assert "tool_call:test_tool" in middleware_calls
        assert "tool_result:test_tool" in middleware_calls


class TestAgentLoopContextInjection:
    """测试 AgentLoop 上下文注入。"""

    @pytest.mark.asyncio
    async def test_agent_loop_tool_with_context_injection(self):
        """工具函数接收上下文注入。"""
        tool_call = ToolCall(
            id="call_1",
            name="context_aware_tool",
            arguments={},
        )
        
        provider = MockToolProvider(tool_calls=[tool_call], final_reply="Done")
        registry = ToolRegistry()
        
        received_contexts = []
        
        @registry.register
        async def context_aware_tool(context: AgentContext) -> str:
            received_contexts.append(context)
            return f"Received {len(context.messages)} messages"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content == "Done"
        assert len(received_contexts) == 1
        assert len(received_contexts[0].messages) >= 2  # 至少有初始消息


class TestAgentLoopEdgeCases:
    """测试 AgentLoop 边界场景。"""

    @pytest.mark.asyncio
    async def test_agent_loop_empty_tool_arguments(self):
        """空参数工具调用。"""
        tool_call = ToolCall(
            id="call_1",
            name="no_args_tool",
            arguments={},
        )
        
        provider = MockToolProvider(tool_calls=[tool_call])
        registry = ToolRegistry()
        
        @registry.register
        async def no_args_tool() -> str:
            return "No args needed"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content

    @pytest.mark.asyncio
    async def test_agent_loop_tool_with_complex_arguments(self):
        """复杂参数工具调用。"""
        tool_call = ToolCall(
            id="call_1",
            name="complex_tool",
            arguments={
                "nested": {"key": "value"},
                "list": [1, 2, 3],
                "mixed": {"a": [1, 2], "b": {"c": 3}},
            },
        )
        
        provider = MockToolProvider(tool_calls=[tool_call])
        registry = ToolRegistry()
        
        @registry.register
        async def complex_tool(nested: dict, list: list, mixed: dict) -> str:
            return "Received complex args"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content

    @pytest.mark.asyncio
    async def test_agent_loop_concurrent_tool_execution(self):
        """并发工具执行（如果支持）。"""
        tool_calls = [
            ToolCall(id="call_1", name="tool_1", arguments={}),
            ToolCall(id="call_2", name="tool_2", arguments={}),
            ToolCall(id="call_3", name="tool_3", arguments={}),
        ]
        
        provider = MockToolProvider(tool_calls=tool_calls)
        registry = ToolRegistry()
        
        execution_order = []
        
        @registry.register
        async def tool_1() -> str:
            execution_order.append("tool_1")
            return "result_1"
        
        @registry.register
        async def tool_2() -> str:
            execution_order.append("tool_2")
            return "result_2"
        
        @registry.register
        async def tool_3() -> str:
            execution_order.append("tool_3")
            return "result_3"
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            response = await loop.run(make_context())

        assert response.content
        assert len(execution_order) == 3

    @pytest.mark.asyncio
    async def test_agent_loop_preserves_message_history(self):
        """验证消息历史正确保留。"""
        tool_call = ToolCall(
            id="call_1",
            name="test_tool",
            arguments={},
        )
        
        provider = MockToolProvider(tool_calls=[tool_call], final_reply="Final answer")
        registry = ToolRegistry()
        
        @registry.register
        async def test_tool() -> str:
            return "Tool result"
        
        initial_messages = [
            Message(role="system", content="System message"),
            Message(role="user", content="User question"),
        ]
        context = AgentContext(messages=initial_messages.copy())
        
        pipeline = Pipeline(provider=provider)
        loop = AgentLoop(pipeline=pipeline, registry=registry)

        async with pipeline:
            await loop.run(context)

        # 验证原始消息未被修改
        assert len(initial_messages) == 2
        # 验证上下文中追加了工具调用和结果
        assert len(context.messages) > len(initial_messages)
