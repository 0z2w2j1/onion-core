# 如何在 Flask/Django 中使用同步 API

本指南展示如何在传统的同步 Web 框架（Flask、Django）中集成 Onion Core。

## 前提条件

- 已了解 [5分钟快速入门](../tutorials/01-quick-start.md)
- 熟悉 Flask 或 Django 基础

## 为什么需要同步 API？

Onion Core 原生是异步的（`async/await`），但 Flask 和 Django（传统模式）是同步框架。直接调用异步代码会导致错误：

```python
# ❌ 错误：在同步函数中调用异步方法
@app.route("/chat")
def chat():
    response = await pipeline.run(ctx)  # SyntaxError!
```

Onion Core 提供了 `run_sync()` 和 `stream_sync()` 方法来解决这个问题。

---

## Flask 集成

### 步骤 1: 安装依赖

```bash
pip install flask onion-core
```

---

### 步骤 2: 创建全局 Pipeline 实例

```python
# app.py
from flask import Flask, request, jsonify
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider
from onion_core.middlewares import (
    SafetyGuardrailMiddleware,
    ObservabilityMiddleware,
)

app = Flask(__name__)

# 创建全局 Pipeline（应用启动时初始化）
pipeline = Pipeline(
    provider=OpenAIProvider(api_key="sk-...", model="gpt-4"),
    max_retries=2,
    provider_timeout=30.0,
)
pipeline.add_middleware(ObservabilityMiddleware())
pipeline.add_middleware(SafetyGuardrailMiddleware())

# 启动 Pipeline
import asyncio
asyncio.run(pipeline.startup())
```

---

### 步骤 3: 使用 run_sync()

```python
@app.route("/chat", methods=["POST"])
def chat():
    """同步聊天接口"""
    try:
        # 获取用户消息
        data = request.json
        user_message = data.get("message", "")
        
        # 创建上下文
        ctx = AgentContext(messages=[
            Message(role="user", content=user_message)
        ])
        
        # 同步执行（内部自动处理事件循环）
        response = pipeline.run_sync(ctx)
        
        # 返回结果
        return jsonify({
            "content": response.content,
            "tokens": response.usage.total_tokens if response.usage else 0,
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

---

### 步骤 4: 流式响应（Server-Sent Events）

```python
from flask import Response

@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    """流式聊天接口（SSE）"""
    data = request.json
    user_message = data.get("message", "")
    
    ctx = AgentContext(messages=[
        Message(role="user", content=user_message)
    ])
    
    def generate():
        """生成 SSE 事件流"""
        try:
            for chunk in pipeline.stream_sync(ctx):
                if chunk.delta:
                    # SSE 格式
                    yield f"data: {chunk.delta}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
        finally:
            yield "data: [DONE]\n\n"
    
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )
```

**前端调用**:
```javascript
const eventSource = new EventSource('/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: "你好" })
});

eventSource.onmessage = (event) => {
    if (event.data === '[DONE]') {
        eventSource.close();
    } else {
        console.log(event.data); // 逐字输出
    }
};
```

---

### 步骤 5: 优雅关闭

```python
import atexit

def shutdown_pipeline():
    """应用关闭时清理资源"""
    asyncio.run(pipeline.shutdown())

atexit.register(shutdown_pipeline)

if __name__ == "__main__":
    app.run(debug=True)
```

---

## Django 集成

### 步骤 1: 安装依赖

```bash
pip install django onion-core
```

---

### 步骤 2: 创建中间件或工具类

```python
# myapp/onion_client.py
import asyncio
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider

class OnionClient:
    _instance = None
    _pipeline = None
    
    @classmethod
    def get_instance(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = cls()
            cls._pipeline = Pipeline(
                provider=OpenAIProvider(api_key="sk-...", model="gpt-4"),
                max_retries=2,
            )
            asyncio.run(cls._pipeline.startup())
        return cls._instance
    
    def chat(self, message: str) -> str:
        """同步聊天方法"""
        ctx = AgentContext(messages=[
            Message(role="user", content=message)
        ])
        response = self._pipeline.run_sync(ctx)
        return response.content

# 全局实例
onion_client = OnionClient.get_instance()
```

---

### 步骤 3: 在视图中使用

```python
# myapp/views.py
from django.http import JsonResponse
from .onion_client import onion_client

def chat_view(request):
    """Django 同步视图"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    import json
    data = json.loads(request.body)
    message = data.get("message", "")
    
    try:
        response_content = onion_client.chat(message)
        return JsonResponse({
            "content": response_content,
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
```

---

### 步骤 4: 配置 URL

```python
# myapp/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("chat/", views.chat_view, name="chat"),
]
```

---

## 高级用法

### 1. 会话管理

为每个用户维护独立的会话历史：

```python
from flask import session

@app.route("/chat", methods=["POST"])
def chat_with_history():
    """带会话历史的聊天"""
    user_id = session.get("user_id", "anonymous")
    
    # 从数据库或缓存加载历史
    history = load_user_history(user_id)
    
    # 创建上下文（包含历史）
    ctx = AgentContext(
        messages=history + [Message(role="user", content=request.json["message"])],
        session_id=user_id,
    )
    
    # 执行请求
    response = pipeline.run_sync(ctx)
    
    # 保存新消息到历史
    save_user_history(user_id, ctx.messages)
    
    return jsonify({"content": response.content})
```

---

### 2. 超时控制

```python
@app.route("/chat", methods=["POST"])
def chat_with_timeout():
    """自定义超时"""
    ctx = AgentContext(messages=[...])
    
    # 覆盖 Pipeline 默认超时
    try:
        response = pipeline.run_sync(ctx, timeout=10.0)  # 10 秒超时
        return jsonify({"content": response.content})
    except TimeoutError:
        return jsonify({"error": "Request timed out"}), 504
```

---

### 3. 异步 Django 视图（Django 3.1+）

如果使用 Django 的异步视图，可以直接使用异步 API：

```python
# myapp/views.py
from django.http import JsonResponse
import asyncio

async def async_chat_view(request):
    """Django 异步视图"""
    import json
    data = json.loads(request.body)
    
    ctx = AgentContext(messages=[
        Message(role="user", content=data["message"])
    ])
    
    # 直接使用异步方法
    response = await pipeline.run(ctx)
    
    return JsonResponse({"content": response.content})
```

---

## 性能优化

### 1. 连接池复用

确保 Pipeline 全局单例，避免重复创建 HTTP 连接：

```python
# ✅ 正确：全局单例
pipeline = Pipeline(provider=OpenAIProvider(...))

# ❌ 错误：每次请求都创建新 Pipeline
@app.route("/chat")
def chat():
    p = Pipeline(provider=OpenAIProvider(...))  # 浪费资源！
    return p.run_sync(ctx)
```

---

### 2. 后台任务处理

对于耗时操作，使用后台任务：

```python
from threading import Thread

def process_in_background(ctx: AgentContext):
    """后台处理函数"""
    response = pipeline.run_sync(ctx)
    # 保存结果到数据库或缓存
    save_result(response)

@app.route("/chat/async", methods=["POST"])
def chat_async():
    """异步处理（立即返回）"""
    ctx = AgentContext(messages=[...])
    
    # 启动后台线程
    thread = Thread(target=process_in_background, args=(ctx,))
    thread.start()
    
    return jsonify({"status": "processing", "request_id": ctx.request_id})
```

---

### 3. 缓存响应

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_chat(message: str) -> str:
    """缓存常见问题的答案"""
    ctx = AgentContext(messages=[Message(role="user", content=message)])
    response = pipeline.run_sync(ctx)
    return response.content

@app.route("/chat", methods=["POST"])
def chat():
    message = request.json["message"]
    content = cached_chat(message)
    return jsonify({"content": content})
```

---

## 常见问题

### Q: run_sync() 可以在 async 函数中调用吗？

A: **不可以**。会抛出 `RuntimeError`：

```python
# ❌ 错误
async def my_async_function():
    response = pipeline.run_sync(ctx)  # RuntimeError!

# ✅ 正确：在 async 上下文中使用异步方法
async def my_async_function():
    response = await pipeline.run(ctx)
```

---

### Q: stream_sync() 的性能如何？

A: `stream_sync()` 会在内存中缓冲所有 chunk，然后逐个 yield。对于长响应，内存占用较高。建议：
- 优先使用异步 `stream()`（如果框架支持）
- 设置 `max_stream_chunks` 限制最大缓冲数

```python
pipeline = Pipeline(
    provider=...,
    max_stream_chunks=5000,  # 限制缓冲大小
)
```

---

### Q: 如何处理并发请求？

A: Flask/Django 通常使用多进程或多线程处理并发。每个 worker 需要独立的 Pipeline 实例：

```python
# Gunicorn 配置（多进程）
# gunicorn_config.py
workers = 4
worker_class = "sync"

# 在每个 worker 中初始化 Pipeline
def post_fork(server, worker):
    global pipeline
    pipeline = Pipeline(provider=OpenAIProvider(...))
    asyncio.run(pipeline.startup())
```

---

## 完整示例：Flask 应用

```python
# app.py
from flask import Flask, request, jsonify, Response
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider
from onion_core.middlewares import SafetyGuardrailMiddleware, ObservabilityMiddleware
import asyncio
import atexit

app = Flask(__name__)

# 初始化 Pipeline
pipeline = Pipeline(
    provider=OpenAIProvider(api_key="sk-...", model="gpt-4-turbo"),
    max_retries=2,
    provider_timeout=30.0,
    enable_circuit_breaker=True,
)
pipeline.add_middleware(ObservabilityMiddleware())
pipeline.add_middleware(SafetyGuardrailMiddleware())
asyncio.run(pipeline.startup())

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    ctx = AgentContext(messages=[
        Message(role="user", content=data["message"])
    ])
    
    try:
        response = pipeline.run_sync(ctx)
        return jsonify({
            "content": response.content,
            "tokens": response.usage.total_tokens if response.usage else 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    data = request.json
    ctx = AgentContext(messages=[
        Message(role="user", content=data["message"])
    ])
    
    def generate():
        try:
            for chunk in pipeline.stream_sync(ctx):
                if chunk.delta:
                    yield f"data: {chunk.delta}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
        finally:
            yield "data: [DONE]\n\n"
    
    return Response(generate(), mimetype="text/event-stream")

def shutdown():
    asyncio.run(pipeline.shutdown())

atexit.register(shutdown)

if __name__ == "__main__":
    app.run(debug=True)
```

运行：
```bash
python app.py
```

测试：
```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

---

## 下一步

- 查看 **[API 参考: Pipeline.run_sync()](../reference/pipeline.md#run_sync)** 了解详细参数
- 阅读 **[背景解释: 异步编程模型](../explanation/async-programming-model.md)** 理解事件循环机制
- 学习 **[操作指南: 解决超时问题](troubleshoot-timeouts.md)** 优化响应速度
