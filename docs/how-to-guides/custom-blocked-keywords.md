# Custom Blocked Keywords

This guide shows how to configure custom blocked keywords for content filtering.

## Overview

Blocked keywords prevent specific terms from being used in prompts or responses, enhancing security and compliance.

## Basic Configuration

```python
from onion_core.middlewares import SafetyMiddleware

safety = SafetyMiddleware(
    blocked_keywords=[
        "password",
        "secret",
        "token",
        "api_key"
    ]
)
```

## Advanced Patterns

### Case-Insensitive Blocking

```python
safety = SafetyMiddleware(
    blocked_keywords=[
        "password",
        "PASSWORD",
        "Password"
    ],
    case_sensitive=False  # Default: True
)
```

### Pattern-Based Blocking

```python
import re

safety = SafetyMiddleware(
    blocked_patterns=[
        r"\b\d{4}-\d{4}-\d{4}-\d{4}\b",  # Credit card numbers
        r"\b\d{3}-\d{2}-\d{4}\b",         # SSN
        r"password\s*[:=]\s*\S+",          # Password assignments
    ]
)
```

## Context-Aware Blocking

### Block Only in Specific Contexts

```python
def custom_block_checker(text: str, context: dict) -> bool:
    """Custom logic to determine if text should be blocked."""
    
    # Block passwords only in user messages
    if context.get("message_type") == "user":
        if "password" in text.lower():
            return True
    
    # Allow technical discussions about passwords
    if "documentation" in context.get("purpose", ""):
        return False
    
    return False

safety = SafetyMiddleware(
    custom_checker=custom_block_checker
)
```

## Dynamic Keyword Lists

### Load from File

```python
import json

def load_blocked_keywords(file_path: str) -> list:
    """Load blocked keywords from JSON file."""
    with open(file_path, 'r') as f:
        return json.load(f)

keywords = load_blocked_keywords("blocked_keywords.json")
safety = SafetyMiddleware(blocked_keywords=keywords)
```

`blocked_keywords.json`:

```json
[
  "password",
  "secret",
  "confidential",
  "classified"
]
```

### Load from Database

```python
import sqlite3

def load_keywords_from_db() -> list:
    """Load blocked keywords from database."""
    conn = sqlite3.connect('config.db')
    cursor = conn.cursor()
    cursor.execute("SELECT keyword FROM blocked_keywords WHERE active=1")
    keywords = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keywords

keywords = load_keywords_from_db()
safety = SafetyMiddleware(blocked_keywords=keywords)
```

## Severity Levels

### Categorize Blocked Keywords

```python
from enum import Enum

class SeverityLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

BLOCKED_KEYWORDS = {
    SeverityLevel.LOW: ["test", "debug"],
    SeverityLevel.MEDIUM: ["password", "secret"],
    SeverityLevel.HIGH: ["credit_card", "ssn"],
    SeverityLevel.CRITICAL: ["admin_access", "master_key"]
}

def check_severity(text: str) -> SeverityLevel:
    """Check severity level of blocked content."""
    for severity, keywords in BLOCKED_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text.lower():
                return severity
    return None

# Usage
severity = check_severity("My password is 12345")
if severity == SeverityLevel.CRITICAL:
    raise SecurityError("Critical content detected!")
elif severity:
    logger.warning(f"{severity.value} content detected")
```

## Custom Actions

### Different Responses per Severity

```python
async def handle_blocked_content(text: str, severity: SeverityLevel):
    """Handle blocked content based on severity."""
    
    if severity == SeverityLevel.CRITICAL:
        # Block request and alert security team
        await send_security_alert(text)
        raise SecurityError("Request blocked: Critical content")
    
    elif severity == SeverityLevel.HIGH:
        # Redact sensitive information
        redacted = redact_sensitive_info(text)
        return redacted
    
    elif severity == SeverityLevel.MEDIUM:
        # Log and continue
        logger.warning(f"Medium severity content: {text}")
        return text
    
    else:
        # Just log
        logger.debug(f"Low severity content: {text}")
        return text
```

## Integration with Pipeline

```python
from onion_core import Pipeline
from onion_core.middlewares import SafetyMiddleware

# Create safety middleware
safety = SafetyMiddleware(
    blocked_keywords=["password", "secret"],
    blocked_patterns=[r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"],
    action="block"  # Options: block, redact, warn
)

# Add to pipeline
pipeline = Pipeline(middlewares=[safety])

# Use pipeline
response = await pipeline.execute(request)
```

## Monitoring and Logging

### Track Blocked Requests

```python
from onion_core.observability import MetricsCollector

metrics = MetricsCollector()

async def track_blocked_requests(text: str, keyword: str):
    """Track blocked requests for monitoring."""
    metrics.increment('safety.blocked_requests', tags={
        'keyword': keyword,
        'length': len(text)
    })
    
    logger.info(
        f"Request blocked due to keyword: {keyword}",
        extra={
            'keyword': keyword,
            'text_length': len(text),
            'timestamp': time.time()
        }
    )
```

## Testing

### Unit Tests

```python
import pytest
from onion_core.middlewares import SafetyMiddleware

@pytest.mark.asyncio
async def test_blocked_keywords():
    safety = SafetyMiddleware(blocked_keywords=["password"])
    
    # Should block
    with pytest.raises(SecurityError):
        await safety.process_request("My password is 123")
    
    # Should allow
    result = await safety.process_request("Hello world")
    assert result is not None

@pytest.mark.asyncio
async def test_pattern_blocking():
    safety = SafetyMiddleware(
        blocked_patterns=[r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"]
    )
    
    # Should block credit card number
    with pytest.raises(SecurityError):
        await safety.process_request("Card: 1234-5678-9012-3456")
```

## Best Practices

1. **Regular Updates**: Review and update blocked keywords regularly
2. **Context Awareness**: Consider context when blocking
3. **Logging**: Log all blocked requests for auditing
4. **Testing**: Test blocking rules thoroughly
5. **Documentation**: Document why keywords are blocked
6. **Graceful Handling**: Provide clear error messages

## Related Topics

- [Customize PII Rules](custom-pii-rules.md)
- [Secure Agent Tutorial](../tutorials/02-secure-agent.md)
