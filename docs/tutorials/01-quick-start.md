# 5分钟快速入门 Onion Core

本教程将带你从零开始，在 5 分钟内安装并运行第一个 Onion Core 应用。

## 前提条件

- Python 3.11 或更高版本
- pip 包管理器

## 第 1 步：安装

```bash
pip install onion-core
```

如果你需要 OpenAI 支持：

```bash
pip install "onion-core[openai]"
```

## 第 2 步：创建第一个 Pipeline

创建一个名为 `hello_onion.py` 的文件：

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message, EchoProvider

async def main():
    # 使用 EchoProvider（无需 API Key，用于测试）
    async with Pipeline(provider=EchoProvider(reply=None)) as p:
        # 创建对话上下文
        ctx = AgentContext(messages=[
            Message(role="user", content="你好，Onion Core！")
        ])
        
        # 执行请求
        response = await p.run(ctx)
        print(f"回复: {response.content}")

if __name__ == "__main__":
    asyncio.run(main())
```

运行它：

```bash
python hello_onion.py
```

你应该看到：

```
回复: 你好，Onion Core！
```

## 第 3 步：添加中间件

现在让我们添加一个可观测性中间件，看看请求的详细信息：

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message, EchoProvider
from onion_core.middlewares import ObservabilityMiddleware

async def main():
    async with Pipeline(provider=EchoProvider(reply=None)) as p:
        # 添加中间件
        p.add_middleware(ObservabilityMiddleware())
        
        ctx = AgentContext(messages=[
            Message(role="user", content="测试可观测性")
        ])
        
        response = await p.run(ctx)
        print(f"回复: {response.content}")
        print(f"耗时: {ctx.metadata.get('duration_s', 0):.4f}秒")

if __name__ == "__main__":
    asyncio.run(main())
```

你会看到结构化日志输出：

```json
{
  "level": "INFO",
  "request_id": "abc123...",
  "trace_id": "def456...",
  "message": "Request completed in 0.0012s"
}
```

## 第 4 步：理解洋葱模型

Onion Core 的核心是**洋葱模型**。每个中间件像一层洋葱皮包裹着 LLM 调用：

```
请求进入 → [追踪] → [监控] → [限流] → [安全] → [LLM] → [安全] → [监控] → [追踪] → 响应返回
```

- **请求阶段**：中间件按优先级**升序**执行（外层到内层）
- **响应阶段**：中间件按优先级**降序**执行（内层到外层）

## 你学到了什么

✅ 如何安装 Onion Core  
✅ 如何创建 Pipeline 和 AgentContext  
✅ 如何添加中间件  
✅ 洋葱模型的基本概念  

## 下一步

继续学习 **[构建安全 Agent](02-secure-agent.md)**，了解如何添加 PII 脱敏、提示词注入防护和上下文窗口管理。
