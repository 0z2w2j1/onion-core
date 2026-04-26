# Configure OpenAI Provider

This guide shows how to configure and use the OpenAI provider in Onion Core.

## Basic Setup

### Install Dependencies

```bash
pip install openai
```

### Basic Configuration

```python
from onion_core.providers import OpenAIProvider
from onion_core.config import OnionConfig

config = OnionConfig(
    api_key="your-openai-api-key",
    provider="openai",
    model="gpt-4"
)

provider = OpenAIProvider(
    api_key=config.api_key,
    model=config.model
)
```

## Advanced Configuration

### Custom Base URL

Use custom endpoints (e.g., Azure OpenAI):

```python
provider = OpenAIProvider(
    api_key="your-api-key",
    model="gpt-4",
    base_url="https://your-resource.openai.azure.com/openai/deployments/your-deployment"
)
```

### Timeout Settings

```python
provider = OpenAIProvider(
    api_key="your-api-key",
    model="gpt-4",
    timeout=30.0,  # Request timeout in seconds
    max_retries=3   # Number of retries
)
```

### Organization ID

```python
provider = OpenAIProvider(
    api_key="your-api-key",
    model="gpt-4",
    organization="org-your-org-id"
)
```

## Model Selection

### Available Models

```python
# GPT-4 models
provider = OpenAIProvider(model="gpt-4")
provider = OpenAIProvider(model="gpt-4-turbo")
provider = OpenAIProvider(model="gpt-4o")

# GPT-3.5 models
provider = OpenAIProvider(model="gpt-3.5-turbo")
provider = OpenAIProvider(model="gpt-3.5-turbo-16k")

# Embedding models
provider = OpenAIProvider(model="text-embedding-ada-002")
```

### Model Parameters

```python
from onion_core.models import ModelParameters

params = ModelParameters(
    temperature=0.7,
    max_tokens=1000,
    top_p=0.9,
    frequency_penalty=0.0,
    presence_penalty=0.0
)

response = await provider.generate(prompt="Hello", params=params)
```

## Streaming Support

### Async Streaming

```python
async def stream_response():
    provider = OpenAIProvider(api_key="your-key", model="gpt-4")
    
    async for chunk in provider.stream_generate("Tell me a story"):
        print(chunk.content, end="", flush=True)

import asyncio
asyncio.run(stream_response())
```

### Sync Streaming

```python
from onion_core.agent import AgentRuntime

agent = AgentRuntime(config=config)

for chunk in agent.stream_sync("Tell me a story"):
    print(chunk.content, end="", flush=True)
```

## Error Handling

### Handle Rate Limits

```python
from openai import RateLimitError
import asyncio

async def generate_with_retry(provider, prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await provider.generate(prompt)
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            
            # Exponential backoff
            wait_time = 2 ** attempt
            print(f"Rate limited. Waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
```

### Handle Authentication Errors

```python
from openai import AuthenticationError

try:
    response = await provider.generate("Hello")
except AuthenticationError:
    print("Invalid API key. Please check your configuration.")
except Exception as e:
    print(f"Error: {e}")
```

## Cost Optimization

### Token Tracking

```python
from onion_core.observability import MetricsCollector

metrics = MetricsCollector()

async def track_token_usage(response):
    usage = response.usage
    metrics.increment('openai.tokens.prompt', usage.prompt_tokens)
    metrics.increment('openai.tokens.completion', usage.completion_tokens)
    metrics.increment('openai.tokens.total', usage.total_tokens)
    
    # Calculate cost (example for gpt-4)
    cost = (usage.prompt_tokens * 0.03 + usage.completion_tokens * 0.06) / 1000
    metrics.increment('openai.cost.usd', cost)
```

### Use Cheaper Models for Simple Tasks

```python
def select_model(task_complexity: str) -> str:
    """Select model based on task complexity."""
    if task_complexity == "simple":
        return "gpt-3.5-turbo"
    elif task_complexity == "medium":
        return "gpt-4"
    else:
        return "gpt-4-turbo"

provider = OpenAIProvider(
    api_key="your-key",
    model=select_model("simple")
)
```

## Monitoring

### Log Requests and Responses

```python
import logging
import json

logger = logging.getLogger(__name__)

async def logged_generate(provider, prompt, **kwargs):
    logger.info(f"OpenAI request: {prompt[:100]}...")
    
    try:
        response = await provider.generate(prompt, **kwargs)
        logger.info(
            f"OpenAI response: {len(response.content)} chars, "
            f"{response.usage.total_tokens} tokens"
        )
        return response
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        raise
```

## Best Practices

1. **Use Environment Variables**: Store API keys securely
2. **Implement Retry Logic**: Handle transient errors
3. **Monitor Token Usage**: Track costs and optimize
4. **Set Timeouts**: Prevent hanging requests
5. **Cache Responses**: Reduce redundant API calls
6. **Choose Appropriate Models**: Balance quality and cost

## Related Topics

- [Configure Domestic AI](configure-domestic-ai.md)
- [Configure Local Models](configure-local-models.md)
- [Setup Fallback Providers](setup-fallback-providers.md)
