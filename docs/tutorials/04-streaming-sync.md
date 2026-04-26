# 流式响应与同步 API 教程

在本教程中，你将学习如何使用流式响应降低延迟，以及如何在 Flask/Django 等同步框架中使用 Onion Core。

## 前提条件

- 已完成 [5分钟快速入门](01-quick-start.md)
- 了解基本的 async/await 语法

---

## 第 1 步：理解流式响应

### 什么是流式响应？

传统模式下，LLM 生成完整个回复后才返回：

```
用户请求 → [等待 5 秒] → 完整回复一次性返回
```

流式模式下，LLM 每生成一个 token 就立即发送：

```
用户请求 → "你" → "好" → "，" → "我" → "是" → ... （逐字输出）
```

**优势**：
- ✅ **更低的首字延迟（TTFT）**：用户几乎立即看到响应
- ✅ **更好的用户体验**：类似打字机效果
- ✅ **更早开始处理**：可以边接收边渲染

---

## 第 2 步：使用异步流式 API

```python
import asyncio
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider

async def main():
    async with Pipeline(provider=OpenAIProvider(api_key="sk-...")) as p:
        ctx = AgentContext(messages=[
            Message(role="user", content="写一首关于春天的诗")
        ])
        
        print("AI: ", end="", flush=True)
        
        # 流式接收
        async for chunk in p.stream(ctx):
            if chunk.delta:  # chunk.delta 包含新生成的文本
                print(chunk.delta, end="", flush=True)
        
        print()  # 换行

if __name__ == "__main__":
    asyncio.run(main())
```

**输出**：
```
AI: 春风拂面柳丝长，
    桃花含笑映阳光。
    燕子归来寻旧巢，
    万物复苏生机盎。
```

每个字几乎立即显示，无需等待整首诗生成完毕。

---

## 第 3 步：流式响应的中间件处理

### PII 脱敏在流式模式下的特殊处理

```python
from onion_core.middlewares import SafetyGuardrailMiddleware

async def streaming_with_pii_masking():
    async with Pipeline(provider=OpenAIProvider(...)) as p:
        p.add_middleware(SafetyGuardrailMiddleware())
        
        ctx = AgentContext(messages=[
            Message(role="user", content="我的电话是多少？")
        ])
        
        # 即使流式输出，PII 也会被正确脱敏
        async for chunk in p.stream(ctx):
            if chunk.delta:
                # 假设 LLM 生成了 "你的电话是 13812345678"
                # SafetyGuardrailMiddleware 会自动脱敏为 "你的电话是 ***"
                print(chunk.delta, end="", flush=True)
```

**实现原理**：
- `SafetyGuardrailMiddleware` 会缓冲最多 **2 秒** 或 **50 个字符**
- 确保 PII 不会被分割到多个 chunk 中
- 然后统一脱敏后输出

**权衡**：
- ⚠️ 引入少量延迟（最多 2 秒）
- ✅ 保证脱敏完整性

---

## 第 4 步：同步流式 API（stream_sync）

如果需要在同步代码中使用流式响应：

```python
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider

def sync_streaming():
    """同步函数中的流式响应"""
    
    pipeline = Pipeline(provider=OpenAIProvider(api_key="sk-..."))
    
    ctx = AgentContext(messages=[
        Message(role="user", content="讲个笑话")
    ])
    
    print("AI: ", end="", flush=True)
    
    # 使用 stream_sync()
    for chunk in pipeline.stream_sync(ctx):
        if chunk.delta:
            print(chunk.delta, end="", flush=True)
    
    print()

# 可以直接调用，无需 asyncio.run()
sync_streaming()
```

**注意**：
- ⚠️ `stream_sync()` 会在内存中缓冲所有 chunk
- ⚠️ 默认最多缓冲 10,000 个 chunk（可通过 `max_stream_chunks` 配置）
- ✅ 适合短响应，长响应建议使用异步 `stream()`

---

## 第 5 步：在 Flask 中使用流式响应

### Server-Sent Events (SSE)

```python
from flask import Flask, Response, request
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider
import asyncio

app = Flask(__name__)

# 全局 Pipeline
pipeline = Pipeline(provider=OpenAIProvider(api_key="sk-..."))
asyncio.run(pipeline.startup())

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
                    # SSE 格式：data: <content>\n\n
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

if __name__ == "__main__":
    app.run(debug=True)
```

---

### 前端调用 SSE

```html
<!DOCTYPE html>
<html>
<body>
    <div id="output"></div>
    
    <script>
        const eventSource = new EventSource('/chat/stream', {
            // 注意：EventSource 不支持 POST，需要使用 fetch + ReadableStream
        });
        
        // 更推荐使用 fetch API
        async function sendMessage(message) {
            const response = await fetch('/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                const text = decoder.decode(value);
                // 解析 SSE 格式
                const lines = text.split('\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const content = line.slice(6);
                        if (content === '[DONE]') {
                            return;
                        }
                        document.getElementById('output').textContent += content;
                    }
                }
            }
        }
        
        sendMessage("你好");
    </script>
</body>
</html>
```

---

## 第 6 步：在 Django 中使用同步 API

### 同步视图

```python
# views.py
from django.http import JsonResponse
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider
import asyncio

# 全局 Pipeline
pipeline = Pipeline(provider=OpenAIProvider(api_key="sk-..."))
asyncio.run(pipeline.startup())

def chat_view(request):
    """Django 同步视图"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    import json
    data = json.loads(request.body)
    
    ctx = AgentContext(messages=[
        Message(role="user", content=data["message"])
    ])
    
    try:
        # 使用 run_sync()
        response = pipeline.run_sync(ctx)
        
        return JsonResponse({
            "content": response.content,
            "tokens": response.usage.total_tokens if response.usage else 0,
        })
    
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
```

---

### 异步视图（Django 3.1+）

```python
async def async_chat_view(request):
    """Django 异步视图"""
    import json
    data = json.loads(request.body)
    
    ctx = AgentContext(messages=[
        Message(role="user", content=data["message"])
    ])
    
    # 直接使用异步方法
    response = await pipeline.run(ctx)
    
    return JsonResponse({
        "content": response.content,
    })
```

---

## 第 7 步：性能对比

### 测试首字延迟（TTFT）

```python
import time
import asyncio

async def test_ttft():
    """测试首字延迟"""
    
    async with Pipeline(provider=OpenAIProvider(...)) as p:
        ctx = AgentContext(messages=[
            Message(role="user", content="写一篇文章")
        ])
        
        # 非流式
        start = time.time()
        response = await p.run(ctx)
        non_streaming_ttft = time.time() - start
        print(f"非流式 TTFT: {non_streaming_ttft:.2f}s")
        
        # 流式
        start = time.time()
        first_token_received = False
        async for chunk in p.stream(ctx):
            if chunk.delta and not first_token_received:
                first_token_received = True
                streaming_ttft = time.time() - start
                print(f"流式 TTFT: {streaming_ttft:.2f}s")
                break
        
        print(f"TTFT 提升: {(non_streaming_ttft - streaming_ttft) / non_streaming_ttft * 100:.1f}%")

asyncio.run(test_ttft())
```

**典型结果**：
```
非流式 TTFT: 5.23s
流式 TTFT: 0.87s
TTFT 提升: 83.4%
```

---

## 第 8 步：处理流式错误

### 捕获流式异常

```python
async def streaming_with_error_handling():
    async with Pipeline(provider=OpenAIProvider(...)) as p:
        ctx = AgentContext(messages=[...])
        
        try:
            async for chunk in p.stream(ctx):
                if chunk.delta:
                    print(chunk.delta, end="", flush=True)
        
        except TimeoutError:
            print("\n❌ 流式响应超时")
        
        except Exception as e:
            print(f"\n❌ 流式错误: {e}")
```

---

## 完整示例：Flask 流式聊天应用

```python
# app.py
from flask import Flask, Response, request, render_template
from onion_core import Pipeline, AgentContext, Message
from onion_core.providers import OpenAIProvider
from onion_core.middlewares import SafetyGuardrailMiddleware
import asyncio

app = Flask(__name__)

# 初始化 Pipeline
pipeline = Pipeline(
    provider=OpenAIProvider(api_key="sk-..."),
    max_retries=2,
)
pipeline.add_middleware(SafetyGuardrailMiddleware())
asyncio.run(pipeline.startup())

@app.route("/")
def index():
    return render_template("chat.html")

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
    
    return Response(
        generate(),
        mimetype="text/event-stream"
    )

if __name__ == "__main__":
    app.run(debug=True)
```

**templates/chat.html**:
```html
<!DOCTYPE html>
<html>
<head>
    <title>Onion Core Chat</title>
</head>
<body>
    <div id="chat"></div>
    <input type="text" id="input" placeholder="输入消息...">
    <button onclick="send()">发送</button>
    
    <script>
        async function send() {
            const input = document.getElementById('input');
            const message = input.value;
            input.value = '';
            
            const response = await fetch('/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            const chat = document.getElementById('chat');
            
            chat.innerHTML += '<p><strong>You:</strong> ' + message + '</p>';
            chat.innerHTML += '<p><strong>AI:</strong> <span id="ai-response"></span></p>';
            
            const aiResponse = document.getElementById('ai-response');
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                const text = decoder.decode(value);
                const lines = text.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const content = line.slice(6);
                        if (content === '[DONE]') return;
                        aiResponse.textContent += content;
                    }
                }
            }
        }
    </script>
</body>
</html>
```

---

## 你学到了什么

✅ 如何使用异步流式 API（`stream()`）  
✅ 如何使用同步流式 API（`stream_sync()`）  
✅ 如何在 Flask/Django 中集成流式响应  
✅ 如何实现 Server-Sent Events (SSE)  
✅ 流式响应的性能优势（TTFT 降低 80%+）  

## 常见陷阱

### 陷阱 1：在 async 上下文中调用 stream_sync()

```python
# ❌ 错误
async def my_function():
    for chunk in pipeline.stream_sync(ctx):  # RuntimeError!
        ...

# ✅ 正确
async def my_function():
    async for chunk in pipeline.stream(ctx):
        ...
```

---

### 陷阱 2：忘记设置 max_stream_chunks

```python
# ❌ 可能 OOM：无限缓冲
pipeline = Pipeline(provider=...)

# ✅ 限制缓冲大小
pipeline = Pipeline(
    provider=...,
    max_stream_chunks=5000,  # 最多缓冲 5000 个 chunk
)
```

---

## 下一步

- 查看 **[操作指南: 在 Flask/Django 中使用同步 API](../how-to-guides/use-sync-api-in-web-frameworks.md)** 了解更多 Web 框架集成
- 阅读 **[背景解释: Pipeline 调度引擎](../explanation/pipeline-scheduling.md)** 理解流式实现原理
- 回顾 **[教程系列总览](README.md)** 探索更多主题

---

**恭喜！你已完成所有 4 篇教程！** 🎉

现在你已经掌握了：
1. ✅ 快速入门和基础用法
2. ✅ 安全护栏和上下文管理
3. ✅ 多 Provider 故障转移
4. ✅ 流式响应和同步 API

继续探索 **[操作指南](../how-to-guides/)** 和 **[背景解释](../explanation/)** 深入学习！
