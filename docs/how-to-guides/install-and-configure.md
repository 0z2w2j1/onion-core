# Install and Configure Onion Core

This guide walks you through installing and configuring Onion Core for your project.

## Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- Virtual environment (recommended)

## Installation

### Step 1: Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 2: Install Onion Core

```bash
pip install onion-core
```

### Step 3: Verify Installation

```python
import onion_core
print(onion_core.__version__)
```

## Basic Configuration

### Minimal Configuration

```python
from onion_core.config import OnionConfig

config = OnionConfig(
    pipeline={
        "max_retries": 2,
        "provider_timeout": 30.0,
    }
)
```

### Full Configuration

```python
from onion_core.config import OnionConfig

config = OnionConfig(
    # Pipeline configuration
    pipeline={
        "timeout": 30.0,
        "max_retries": 3,
        "retry_delay": 1.0
    },
    
    # Safety configuration
    safety={
        "enabled": True,
        "pii_detection": True,
        "blocked_keywords": ["password", "secret"]
    },
    
    # Context window configuration
    context_window={
        "max_tokens": 8000,
        "max_messages": 50
    },
    
    # Observability configuration
    observability={
        "logging_enabled": True,
        "metrics_enabled": True,
        "tracing_enabled": True,
    },
    
    # Concurrency configuration
    concurrency={
        "max_workers": 10,
        "task_queue_size": 100,
    },
)
```

## Environment Variables

You can configure Onion Core using environment variables:

```bash
export ONION__PIPELINE__MAX_RETRIES="3"
export ONION__PIPELINE__PROVIDER_TIMEOUT="30"
export ONION__SAFETY__ENABLE_PII_MASKING="true"
export ONION__CONTEXT_WINDOW__MAX_TOKENS="8000"
```

Then load them in your code:

```python
from onion_core.config import OnionConfig

config = OnionConfig.from_env()
```

## Loading from File

### YAML Configuration

Create `config.yaml`:

```yaml
pipeline:
  timeout: 30.0
  max_retries: 3

safety:
  enable_pii_masking: true

context_window:
  max_tokens: 8000
  max_messages: 50
```

Load the configuration:

```python
import yaml
from onion_core.config import OnionConfig

with open("config.yaml", "r") as f:
    config_dict = yaml.safe_load(f)

config = OnionConfig(**config_dict)
```

### JSON Configuration

Create `config.json`:

```json
{
  "pipeline": {
    "timeout": 30.0,
    "max_retries": 3
  },
  "safety": {
    "enable_pii_masking": true
  }
}
```

Load the configuration:

```python
import json
from onion_core.config import OnionConfig

with open("config.json", "r") as f:
    config_dict = json.load(f)

config = OnionConfig(**config_dict)
```

## Provider-Specific Configuration

### OpenAI

```python
from onion_core.providers import OpenAIProvider

provider = OpenAIProvider(
    api_key="your-openai-key",
    model="gpt-4",
    base_url=None,  # Optional: custom endpoint
    timeout=30.0
)
```

### Anthropic

```python
from onion_core.providers import AnthropicProvider

provider = AnthropicProvider(
    api_key="your-anthropic-key",
    model="claude-3-opus",
    timeout=30.0
)
```

### Local Models (Ollama)

```python
from onion_core.providers import OllamaProvider

provider = OllamaProvider(
    base_url="http://localhost:11434",
    model="llama2",
    timeout=60.0
)
```

## Testing Configuration

### Health Check

```python
from onion_core.agent import AgentRuntime
from onion_core import AgentContext, Message

agent = AgentRuntime(config=config)

async def test_connection():
    try:
        ctx = AgentContext(messages=[Message(role="user", content="Hello, world!")])
        response = await agent.run(ctx)
        print(f"Success: {response}")
    except Exception as e:
        print(f"Error: {e}")

import asyncio
asyncio.run(test_connection())
```

### Configuration Validation

```python
from onion_core.config import OnionConfig

try:
    config = OnionConfig(
        pipeline={
            "max_retries": -1,  # This will raise a validation error
        },
    )
except ValueError as e:
    print(f"Invalid configuration: {e}")
```

## Troubleshooting

### Issue: Import Error

**Problem**: `ModuleNotFoundError: No module named 'onion_core'`

**Solution**:
```bash
pip install onion-core
# Or if using virtual environment, make sure it's activated
source venv/bin/activate
```

### Issue: API Key Not Found

**Problem**: `ValueError: API key is required`

**Solution**:
```python
import os
os.environ["ONION_API_KEY"] = "your-api-key"
```

### Issue: Connection Timeout

**Problem**: Requests timing out

**Solution**:
```python
config = OnionConfig(
    pipeline={
        "timeout": 60.0,  # Increase timeout
        "max_retries": 5,   # Increase retries
    },
)
```

## Next Steps

- [Quick Start Tutorial](../tutorials/01-quick-start.md)
- [Configure Providers](configure-openai-provider.md)
- [Setup Fallback Providers](setup-fallback-providers.md)
