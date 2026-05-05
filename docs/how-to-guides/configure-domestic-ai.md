# Configure Domestic AI Providers

This guide shows how to configure Chinese domestic AI providers like DeepSeek, Zhipu AI, Moonshot, and DashScope.

## DeepSeek

### Installation

```bash
pip install deepseek-ai
```

### Configuration

```python
from onion_core.providers import DeepSeekProvider

provider = DeepSeekProvider(
    api_key="your-deepseek-api-key",
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1"
)
```

### Usage

```python
from onion_core.models import AgentContext

context = AgentContext(messages=[{"role": "user", "content": "你好，请介绍一下自己"}])
response = await provider.complete(context)
print(response.content)
```

## Zhipu AI (智谱AI)

### Installation

```bash
pip install zhipuai
```

### Configuration

```python
from onion_core.providers import ZhipuAIProvider

provider = ZhipuAIProvider(
    api_key="your-zhipu-api-key",
    model="glm-4",
    base_url="https://open.bigmodel.cn/api/paas/v4"
)
```

### Available Models

```python
# GLM models
models = [
    "glm-4",        # Latest version
    "glm-3-turbo",  # Fast and efficient
    "glm-4v",       # Vision capabilities
]
```

## Moonshot (月之暗面)

### Installation

```bash
pip install moonshot-ai
```

### Configuration

```python
from onion_core.providers import MoonshotProvider

provider = MoonshotProvider(
    api_key="your-moonshot-api-key",
    model="moonshot-v1-8k",
    base_url="https://api.moonshot.cn/v1"
)
```

### Model Options

```python
models = {
    "moonshot-v1-8k": "8K context window",
    "moonshot-v1-32k": "32K context window",
    "moonshot-v1-128k": "128K context window"
}
```

## DashScope (阿里云通义千问)

### Installation

```bash
pip install dashscope
```

### Configuration

```python
from onion_core.providers import DashScopeProvider

provider = DashScopeProvider(
    api_key="your-dashscope-api-key",
    model="qwen-max",
    base_url="https://dashscope.aliyuncs.com/api/v1"
)
```

### Available Models

```python
models = [
    "qwen-max",          # Most capable
    "qwen-plus",         # Balanced
    "qwen-turbo",        # Fast and cheap
    "qwen-long",         # Long context
]
```

## Fallback Configuration

### Setup Multiple Providers

```python
from onion_core.providers import (
    DeepSeekProvider,
    ZhipuAIProvider,
    MoonshotProvider
)
from onion_core.models import AgentContext

# Define providers with priorities
providers = [
    ("deepseek", DeepSeekProvider(api_key="key1", model="deepseek-chat"), 1),
    ("zhipu", ZhipuAIProvider(api_key="key2", model="glm-4"), 2),
    ("moonshot", MoonshotProvider(api_key="key3", model="moonshot-v1-8k"), 3),
]

# Try primary first, fall back to alternates
async def generate_with_fallback(context):
    for name, provider, priority in sorted(providers, key=lambda x: x[2]):
        try:
            return await provider.complete(context)
        except Exception as e:
            logger.warning(f"Provider {name} failed: {e}")
            continue
    raise RuntimeError("All providers exhausted")
```

## Environment Variables

```bash
export DEEPSEEK_API_KEY="your-deepseek-key"
export ZHIPU_API_KEY="your-zhipu-key"
export MOONSHOT_API_KEY="your-moonshot-key"
export DASHSCOPE_API_KEY="your-dashscope-key"
```

Load in code:

```python
import os
from onion_core.providers import DeepSeekProvider

provider = DeepSeekProvider(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    model="deepseek-chat"
)
```

## Cost Comparison

| Provider | Model | Input (¥/1K tokens) | Output (¥/1K tokens) |
|----------|-------|---------------------|----------------------|
| DeepSeek | deepseek-chat | 0.001 | 0.002 |
| Zhipu AI | glm-4 | 0.1 | 0.1 |
| Moonshot | moonshot-v1-8k | 0.012 | 0.012 |
| DashScope | qwen-max | 0.04 | 0.12 |

## Best Practices

1. **Use Fallbacks**: Configure multiple providers for reliability
2. **Monitor Costs**: Track token usage across providers
3. **Test Models**: Evaluate quality for your use case
4. **Cache Responses**: Reduce API calls and costs
5. **Handle Rate Limits**: Implement retry logic

## Related Topics

- [Configure OpenAI Provider](configure-openai-provider.md)
- [Setup Fallback Providers](setup-fallback-providers.md)
- [Configure Local Models](configure-local-models.md)
