# Configure Local Models

This guide shows how to configure local AI models using Ollama and LM Studio.

## Why Use Local Models?

- **Privacy**: Data stays on your machine
- **Cost**: No API fees
- **Customization**: Fine-tune for specific tasks
- **Offline**: Works without internet
- **Control**: Full control over model behavior

## Ollama

### Installation

1. Download from [ollama.ai](https://ollama.ai)
2. Install on your system
3. Pull a model:

```bash
ollama pull llama2
ollama pull mistral
ollama pull codellama
```

### Start Ollama Server

```bash
ollama serve
```

Server runs at `http://localhost:11434` by default.

### Configuration

```python
from onion_core.providers import OllamaProvider

provider = OllamaProvider(
    base_url="http://localhost:11434",
    model="llama2",
    timeout=60.0
)
```

### Available Models

```bash
# General purpose
ollama pull llama2
ollama pull mistral
ollama pull gemma

# Coding
ollama pull codellama
ollama pull starcoder

# Specialized
ollama pull llama2-uncensored
ollama pull dolphin-mistral
```

### Advanced Configuration

```python
provider = OllamaProvider(
    base_url="http://localhost:11434",
    model="llama2",
    timeout=60.0,
    options={
        "temperature": 0.7,
        "top_p": 0.9,
        "num_ctx": 4096,
        "num_gpu_layers": 32
    }
)
```

## LM Studio

### Installation

1. Download from [lmstudio.ai](https://lmstudio.ai)
2. Install on your system
3. Download models through the UI

### Start Local Server

1. Open LM Studio
2. Go to "Local Server" tab
3. Click "Start Server"

Server runs at `http://localhost:1234/v1` by default.

### Configuration

```python
from onion_core.providers import LMStudioProvider

provider = LMStudioProvider(
    base_url="http://localhost:1234/v1",
    model="local-model",
    timeout=60.0
)
```

### Load GGUF Models

1. Download GGUF models from HuggingFace
2. Import into LM Studio
3. Select model in UI
4. Start server

## Usage Examples

### Basic Generation

```python
from onion_core.agent import AgentRuntime
from onion_core.config import OnionConfig
from onion_core.models import AgentContext

config = OnionConfig(
    provider="ollama",
    model="llama2"
)

agent = AgentRuntime(config=config)

async def chat():
    ctx = AgentContext(messages=[{"role": "user", "content": "Explain quantum computing"}])
    response = await agent.run(ctx)
    print(response.content)

import asyncio
asyncio.run(chat())
```

### Streaming

```python
async def stream_chat():
    async for chunk in agent.stream_async("Tell me a story"):
        print(chunk.content, end="", flush=True)

asyncio.run(stream_chat())
```

## Performance Optimization

### GPU Acceleration

#### Ollama with GPU

```bash
# Check GPU availability
ollama run llama2 "/bye"

# Set GPU layers
export OLLAMA_NUM_GPU_LAYERS=32
ollama serve
```

#### LM Studio with GPU

1. Open LM Studio settings
2. Enable GPU acceleration
3. Select GPU device
4. Adjust GPU layers

### Memory Management

```python
# Limit context window
provider = OllamaProvider(
    model="llama2",
    options={
        "num_ctx": 2048  # Reduce memory usage
    }
)
```

### Quantization

Use quantized models for better performance:

```bash
# Pull quantized model
ollama pull llama2:7b-q4_0

# Available quantizations
# q4_0: Good balance of speed and quality
# q4_k_m: Better quality, slightly slower
# q8_0: Best quality, slowest
```

## Model Comparison

| Model | Size | Quality | Speed | RAM Required |
|-------|------|---------|-------|--------------|
| Llama2 7B | 3.8GB | Good | Fast | 8GB |
| Llama2 13B | 7.4GB | Better | Medium | 16GB |
| Mistral 7B | 3.8GB | Good | Fast | 8GB |
| Codellama 7B | 3.8GB | Good (code) | Fast | 8GB |
| Gemma 7B | 3.8GB | Good | Fast | 8GB |

## Troubleshooting

### Issue: Connection Refused

**Problem**: Cannot connect to Ollama/LM Studio

**Solution**:
```bash
# Check if server is running
curl http://localhost:11434/api/tags  # Ollama
curl http://localhost:1234/v1/models  # LM Studio

# Restart server
ollama serve
# or restart LM Studio server
```

### Issue: Out of Memory

**Problem**: Model too large for available RAM

**Solution**:
1. Use smaller model (7B instead of 13B)
2. Use quantized version (q4_0)
3. Reduce context window
4. Close other applications

### Issue: Slow Response

**Problem**: Generation is very slow

**Solution**:
1. Enable GPU acceleration
2. Use smaller model
3. Reduce max_tokens
4. Increase temperature for faster sampling

## Integration with Pipeline

```python
from onion_core import Pipeline
from onion_core.middlewares import (
    SafetyGuardrailMiddleware,
    ContextWindowMiddleware,
    ResponseCacheMiddleware
)
from onion_core.providers import OllamaProvider

# Create pipeline with local model
pipeline = Pipeline()
pipeline.add_middleware(SafetyGuardrailMiddleware())
pipeline.add_middleware(ContextWindowMiddleware(max_tokens=4096))
pipeline.add_middleware(ResponseCacheMiddleware(ttl=300))

provider = OllamaProvider(model="llama2")

# Use pipeline
response = await pipeline.run(context)
```

## Best Practices

1. **Start Small**: Begin with 7B models
2. **Use GPU**: Enable GPU acceleration when possible
3. **Quantize**: Use q4_0 or q4_k_m quantization
4. **Monitor Resources**: Watch CPU/GPU/RAM usage
5. **Cache Responses**: Reduce redundant computations
6. **Test Locally**: Verify quality before production

## Related Topics

- [Configure OpenAI Provider](configure-openai-provider.md)
- [Configure Domestic AI](configure-domestic-ai.md)
- [Memory Management](../explanation/memory-management.md)
