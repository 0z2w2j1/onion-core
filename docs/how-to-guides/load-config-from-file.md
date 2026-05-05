# Load Configuration from File

This guide shows how to load Onion Core configuration from external files.

## Why Use Configuration Files?

- **Separation of Concerns**: Keep config separate from code
- **Environment-Specific Settings**: Different configs for dev/staging/prod
- **Version Control**: Track configuration changes
- **Easy Updates**: Modify settings without code changes

## YAML Configuration

### Install PyYAML

```bash
pip install pyyaml
```

### Create Configuration File

Create `config.yaml`:

```yaml
# Pipeline settings
pipeline:
  max_retries: 3
  provider_timeout: 30.0
  enable_circuit_breaker: true

# Safety settings
safety:
  enable_pii_masking: true
  blocked_keywords:
    - "password"
    - "secret"
    - "token"

# Context window settings
context_window:
  max_tokens: 8000
  keep_rounds: 2
  encoding_name: "cl100k_base"

# Observability settings
observability:
  log_level: "INFO"
  log_tool_args: true

# Concurrency settings
concurrency:
  tool_concurrency: 10
  llm_max_connections: 100
```

### Load YAML Configuration

```python
import os
import yaml
from onion_core.config import OnionConfig

def load_config_from_yaml(file_path: str) -> OnionConfig:
    """Load configuration from YAML file."""
    with open(file_path, 'r') as f:
        config_dict = yaml.safe_load(f)
    
    # Expand environment variables
    def expand_env_vars(obj):
        if isinstance(obj, str):
            if obj.startswith("${") and obj.endswith("}"):
                env_var = obj[2:-1]
                return os.getenv(env_var, obj)
            return obj
        elif isinstance(obj, dict):
            return {k: expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [expand_env_vars(item) for item in obj]
        return obj
    
    config_dict = expand_env_vars(config_dict)
    
    return OnionConfig(**config_dict)

# Usage
config = load_config_from_yaml("config.yaml")
```

## JSON Configuration

### Create Configuration File

Create `config.json`:

```json
{
  "pipeline": {
    "max_retries": 3,
    "provider_timeout": 30.0
  },
  "safety": {
    "enable_pii_masking": true,
    "blocked_keywords": ["password", "secret"]
  },
  "context_window": {
    "max_tokens": 8000,
    "keep_rounds": 2
  }
}
```

### Load JSON Configuration

```python
import os
import json
from onion_core.config import OnionConfig

def load_config_from_json(file_path: str) -> OnionConfig:
    """Load configuration from JSON file."""
    with open(file_path, 'r') as f:
        config_dict = json.load(f)
    
    # Expand environment variables (same function as above)
    def expand_env_vars(obj):
        if isinstance(obj, str):
            if obj.startswith("${") and obj.endswith("}"):
                env_var = obj[2:-1]
                return os.getenv(env_var, obj)
            return obj
        elif isinstance(obj, dict):
            return {k: expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [expand_env_vars(item) for item in obj]
        return obj
    
    config_dict = expand_env_vars(config_dict)
    
    return OnionConfig(**config_dict)

# Usage
config = load_config_from_json("config.json")
```

## TOML Configuration

### Install toml

```bash
pip install toml
```

### Create Configuration File

Create `config.toml`:

```toml
[pipeline]
max_retries = 3
provider_timeout = 30.0

[safety]
enable_pii_masking = true
blocked_keywords = ["password", "secret"]

[context_window]
max_tokens = 8000
keep_rounds = 2
```

### Load TOML Configuration

```python
import os
import toml
from onion_core.config import OnionConfig

def load_config_from_toml(file_path: str) -> OnionConfig:
    """Load configuration from TOML file."""
    with open(file_path, 'r') as f:
        config_dict = toml.load(f)
    
    # Expand environment variables
    # ... (same expand_env_vars function)
    
    return OnionConfig(**config_dict)

# Usage
config = load_config_from_toml("config.toml")
```

## Multiple Environment Configs

### Directory Structure

```
config/
├── base.yaml
├── development.yaml
├── staging.yaml
└── production.yaml
```

### Base Configuration

`config/base.yaml`:

```yaml
pipeline:
  provider_timeout: 30.0
  max_retries: 3

safety:
  enable_pii_masking: true
  blocked_keywords: ["password", "secret"]
```

### Development Configuration

`config/development.yaml`:

```yaml
# Inherits from base.yaml
observability:
  log_level: "DEBUG"
  log_tool_args: true

concurrency:
  tool_concurrency: 2
```

### Production Configuration

`config/production.yaml`:

```yaml
# Inherits from base.yaml
pipeline:
  provider_timeout: 60.0
  max_retries: 5

observability:
  log_level: "WARNING"
  log_tool_args: false

concurrency:
  tool_concurrency: 20
  llm_max_connections: 50
```

### Load Environment-Specific Config

```python
import os
import yaml
from pathlib import Path

def load_environment_config(env: str = "development") -> OnionConfig:
    """Load configuration for specific environment."""
    config_dir = Path("config")
    
    # Load base config
    with open(config_dir / "base.yaml", 'r') as f:
        base_config = yaml.safe_load(f)
    
    # Load environment-specific config
    env_config_path = config_dir / f"{env}.yaml"
    if env_config_path.exists():
        with open(env_config_path, 'r') as f:
            env_config = yaml.safe_load(f)
        
        # Merge configs (env overrides base)
        merged_config = {**base_config, **env_config}
    else:
        merged_config = base_config
    
    return OnionConfig(**merged_config)

# Usage
env = os.getenv("APP_ENV", "development")
config = load_environment_config(env)
```

## Validation

### Schema Validation with Pydantic

```python
from pydantic import BaseModel, Field, ValidationError
import yaml

class PipelineValidationSchema(BaseModel):
    provider_timeout: float = Field(ge=1.0, le=300.0, default=30.0)
    max_retries: int = Field(ge=0, le=10, default=3)
    enable_circuit_breaker: bool = True

class ConfigSchema(BaseModel):
    pipeline: PipelineValidationSchema = Field(default_factory=PipelineValidationSchema)

def validate_config(file_path: str) -> bool:
    """Validate configuration file against schema."""
    with open(file_path, 'r') as f:
        config_dict = yaml.safe_load(f)
    
    try:
        ConfigSchema(**config_dict)
        return True
    except ValidationError as e:
        print(f"Configuration validation failed: {e}")
        return False

# Usage
if validate_config("config.yaml"):
    config = load_config_from_yaml("config.yaml")
```

## Best Practices

1. **Use Environment Variables for Secrets**: Never hardcode API keys
2. **Version Control Config Files**: Track changes in git
3. **Document Configuration Options**: Add comments to config files
4. **Validate Before Loading**: Check config validity early
5. **Provide Defaults**: Use sensible defaults for optional settings
6. **Separate Environments**: Maintain different configs for dev/staging/prod

## Related Topics

- [Install and Configure](install-and-configure.md)
- [Configure OpenAI Provider](configure-openai-provider.md)
- [Setup Fallback Providers](setup-fallback-providers.md)
