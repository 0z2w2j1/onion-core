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
    api_key="your-api-key",
    provider="openai",
    model="gpt-4"
)
```

### Full Configuration

```python
from onion_core.config import (
    OnionConfig,
    PipelineConfig,
    SafetyConfig,
    ContextWindowConfig,
    ObservabilityConfig,
    ConcurrencyConfig
)

config = OnionConfig(
    # Provider settings
    api_key="your-api-key",
    provider="openai",
    model="gpt-4",
    
    # Pipeline configuration
    pipeline=PipelineConfig(
        timeout=30.0,
        max_retries=3,
        retry_delay=1.0
    ),
    
    # Safety configuration
    safety=SafetyConfig(
        enabled=True,
        pii_detection=True,
        blocked_keywords=["password", "secret"]
    ),
    
    # Context window configuration
    context_window=ContextWindowConfig(
        max_tokens=8000,
        max_messages=50
    ),
    
    # Observability configuration
    observability=ObservabilityConfig(
        logging_enabled=True,
        metrics_enabled=True,
        tracing_enabled=True
    ),
    
    # Concurrency configuration
    concurrency=ConcurrencyConfig(
        max_workers=10,
        task_queue_size=100
    )
)
```

## Environment Variables

You can configure Onion Core using environment variables:

```bash
export ONION_API_KEY="your-api-key"
export ONION_PROVIDER="openai"
export ONION_MODEL="gpt-4"
export ONION_TIMEOUT="30"
export ONION_MAX_RETRIES="3"
```

Then load them in your code:

```python
import os
from onion_core.config import OnionConfig

config = OnionConfig(
    api_key=os.getenv("ONION_API_KEY"),
    provider=os.getenv("ONION_PROVIDER", "openai"),
    model=os.getenv("ONION_MODEL", "gpt-4")
)
```

## Loading from File

### YAML Configuration

Create `config.yaml`:

```yaml
api_key: "your-api-key"
provider: "openai"
model: "gpt-4"

pipeline:
  timeout: 30.0
  max_retries: 3

safety:
  enabled: true
  pii_detection: true

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
  "api_key": "your-api-key",
  "provider": "openai",
  "model": "gpt-4",
  "pipeline": {
    "timeout": 30.0,
    "max_retries": 3
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

agent = AgentRuntime(config=config)

async def test_connection():
    try:
        response = await agent.run_async("Hello, world!")
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
        api_key="your-key",
        provider="invalid-provider"  # This will raise an error
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
    pipeline=PipelineConfig(
        timeout=60.0,  # Increase timeout
        max_retries=5   # Increase retries
    )
)
```

## Next Steps

- [Quick Start Tutorial](../tutorials/01-quick-start.md)
- [Configure Providers](configure-openai-provider.md)
- [Setup Fallback Providers](setup-fallback-providers.md)
