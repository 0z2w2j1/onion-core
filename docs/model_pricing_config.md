# 模型定价配置指南

> **问题**：LLM 厂商（OpenAI、Anthropic 等）会频繁调整 API 价格，硬编码在代码中的定价表很快就会过时。

> **解决方案**：Onion Core v0.9.1+ 提供多层级定价配置机制，支持动态更新而无需修改代码。

---

## 🎯 定价配置优先级

```
运行时 custom_pricing > 环境变量 ONION_MODEL_PRICING > 代码默认值 MODEL_PRICING
```

---

## 方法 1：环境变量（推荐用于生产环境）

### 基本用法

```bash
# Linux/macOS
export ONION_MODEL_PRICING='{"gpt-4o": [0.0025, 0.0075], "custom-model": [0.001, 0.002]}'

# Windows PowerShell
$env:ONION_MODEL_PRICING='{"gpt-4o": [0.0025, 0.0075], "custom-model": [0.001, 0.002]}'

# Windows CMD
set ONION_MODEL_PRICING={"gpt-4o": [0.0025, 0.0075], "custom-model": [0.001, 0.002]}
```

### Python 代码

```python
from onion_core import Pipeline
from onion_core.observability.metrics import MetricsMiddleware

# 自动从环境变量加载定价
pipeline = Pipeline(provider=my_provider)
pipeline.add_middleware(MetricsMiddleware(pipeline_name="prod-agent"))
```

### Kubernetes 部署

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: onion-core-agent
spec:
  template:
    spec:
      containers:
      - name: agent
        image: onion-core:0.9.1
        env:
        - name: ONION_MODEL_PRICING
          value: |
            {
              "gpt-4o": [0.0025, 0.0075],
              "gpt-4o-mini": [0.000075, 0.0003],
              "claude-3-5-sonnet": [0.003, 0.015]
            }
```

### Docker Compose

```yaml
version: '3.8'
services:
  agent:
    image: onion-core:0.9.1
    environment:
      ONION_MODEL_PRICING: >
        {
          "gpt-4o": [0.0025, 0.0075],
          "custom-finetuned": [0.001, 0.002]
        }
```

---

## 方法 2：运行时自定义定价（推荐用于多租户场景）

### 基础用法

```python
from onion_core.observability.metrics import MetricsMiddleware

# 为不同租户使用不同定价
tenant_a_pricing = {
    "gpt-4o": (0.003, 0.009),  # 企业折扣价
    "custom-model": (0.001, 0.002),
}

middleware = MetricsMiddleware(
    pipeline_name="tenant-a",
    custom_pricing=tenant_a_pricing,
)
```

### 从配置文件加载

```python
import yaml
from onion_core.observability.metrics import MetricsMiddleware

# pricing.yaml
# ---
# gpt-4o: [0.0025, 0.0075]
# claude-3-opus: [0.012, 0.060]

with open("pricing.yaml") as f:
    pricing_config = yaml.safe_load(f)

# 转换为 tuple 格式
custom_pricing = {k: tuple(v) for k, v in pricing_config.items()}

middleware = MetricsMiddleware(
    pipeline_name="prod",
    custom_pricing=custom_pricing,
)
```

### 从数据库/API 动态加载

```python
import requests
from onion_core.observability.metrics import MetricsMiddleware

def fetch_latest_pricing() -> dict[str, tuple[float, float]]:
    """从内部定价服务获取最新价格"""
    response = requests.get("https://internal-api.company.com/llm-pricing")
    response.raise_for_status()
    
    pricing_data = response.json()
    return {k: tuple(v) for k, v in pricing_data.items()}

# 启动时加载最新价格
latest_pricing = fetch_latest_pricing()

middleware = MetricsMiddleware(
    pipeline_name="prod",
    custom_pricing=latest_pricing,
)
```

---

## 方法 3：直接修改代码默认值（不推荐）

仅在以下场景使用：
- 开发/测试环境
- 无外部配置能力的场景

```python
# onion_core/observability/metrics.py

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # 手动更新这里（需要重新部署）
    "gpt-4o": (0.0025, 0.0075),  # ← 价格变了就改这里
    "gpt-4o-mini": (0.000075, 0.0003),
    ...
}
```

⚠️ **缺点**：每次价格调整都需要修改代码、提交 Git、重新部署。

---

## 📊 完整示例：生产环境最佳实践

### 项目结构

```
my-project/
├── config/
│   ├── pricing.prod.yaml      # 生产环境定价
│   ├── pricing.staging.yaml   # 测试环境定价
│   └── pricing.dev.yaml       # 开发环境定价
├── app.py
└── requirements.txt
```

### 配置文件示例

**config/pricing.prod.yaml**
```yaml
# 生产环境：使用企业折扣价
gpt-4o: [0.0025, 0.0075]
gpt-4o-mini: [0.000075, 0.0003]
claude-3-5-sonnet: [0.003, 0.015]
claude-3-haiku: [0.00025, 0.00125]
```

**config/pricing.dev.yaml**
```yaml
# 开发环境：使用公开价格（便于对比成本）
gpt-4o: [0.005, 0.015]
gpt-4o-mini: [0.00015, 0.0006]
```

### 应用代码

```python
import os
import yaml
from pathlib import Path
from onion_core import Pipeline, OpenAIProvider
from onion_core.observability.metrics import MetricsMiddleware

def load_pricing_config() -> dict[str, tuple[float, float]]:
    """根据环境加载定价配置"""
    env = os.getenv("APP_ENV", "dev")
    pricing_file = Path(__file__).parent / "config" / f"pricing.{env}.yaml"
    
    if not pricing_file.exists():
        print(f"Warning: Pricing file not found: {pricing_file}")
        return {}
    
    with open(pricing_file) as f:
        config = yaml.safe_load(f)
    
    return {k: tuple(v) for k, v in config.items()}

# 初始化 Pipeline
provider = OpenAIProvider(api_key=os.getenv("OPENAI_API_KEY"))
pipeline = Pipeline(provider=provider)

# 添加带自定义定价的指标中间件
custom_pricing = load_pricing_config()
metrics = MetricsMiddleware(
    pipeline_name="production-agent",
    custom_pricing=custom_pricing if custom_pricing else None,
)
pipeline.add_middleware(metrics)

print(f"Loaded pricing for {len(custom_pricing)} models")
```

### 部署脚本

```bash
#!/bin/bash
# deploy.sh

# 设置环境
export APP_ENV=prod

# 启动服务
python app.py
```

---

## 🔍 验证配置是否生效

### 方法 1：检查日志

```python
import logging
logging.basicConfig(level=logging.INFO)

# 启动时会看到：
# INFO:onion_core.metrics:Loaded model pricing from environment variables
```

### 方法 2：查询 Prometheus 指标

```promql
# 查看是否有成本数据
onion_token_cost_usd

# 如果返回空，说明定价配置未生效或没有请求
```

### 方法 3：单元测试

```python
from onion_core.observability.metrics import calculate_cost

# 测试默认定价
cost = calculate_cost("gpt-4o", 1000, 500)
assert cost == 0.0125  # 0.005 + 0.0075

# 测试自定义定价
custom = {"gpt-4o": (0.0025, 0.0075)}
cost = calculate_cost("gpt-4o", 1000, 500, custom_pricing=custom)
assert cost == 0.00625  # 0.0025 + 0.00375
```

---

## 💡 最佳实践建议

### ✅ 推荐做法

1. **生产环境使用环境变量或配置文件**
   ```bash
   export ONION_MODEL_PRICING='{"gpt-4o": [0.0025, 0.0075]}'
   ```

2. **定期更新定价**（建议每月检查一次）
   - OpenAI: https://openai.com/api/pricing/
   - Anthropic: https://www.anthropic.com/pricing
   - Azure OpenAI: https://azure.microsoft.com/pricing/

3. **为不同环境使用不同定价**
   - Dev/Staging: 使用公开价格
   - Production: 使用企业折扣价

4. **监控成本异常**
   ```promql
   # Alertmanager 规则
   groups:
   - name: cost_alerts
     rules:
     - alert: HighTokenCost
       expr: increase(onion_token_cost_usd[1h]) > 100
       annotations:
         summary: "High LLM token cost detected"
   ```

### ❌ 避免的做法

1. **不要硬编码在代码中**（除非是 fallback）
2. **不要忘记更新定价**（会导致成本统计不准确）
3. **不要在多个地方维护定价**（容易不一致）

---

## 🔄 价格变更时的操作流程

### 场景：OpenAI 宣布 GPT-4o 降价 50%

**步骤 1：更新配置**

```bash
# 方式 A：更新环境变量
export ONION_MODEL_PRICING='{"gpt-4o": [0.0025, 0.0075]}'

# 方式 B：更新配置文件
# config/pricing.prod.yaml
# gpt-4o: [0.0025, 0.0075]  # ← 从 [0.005, 0.015] 改为 [0.0025, 0.0075]
```

**步骤 2：重启服务**

```bash
# Kubernetes
kubectl rollout restart deployment/onion-core-agent

# Docker
docker-compose restart agent

# 传统部署
systemctl restart onion-core
```

**步骤 3：验证**

```python
# 发送测试请求并检查 Prometheus 指标
curl http://localhost:8000/metrics | grep onion_token_cost_usd
```

✅ **完成！无需修改代码、无需重新构建镜像。**

---

## 📚 相关文档

- [Prometheus 指标文档](monitoring_guide.md)
- [分布式能力使用指南](distributed_usage.md)
- [成本优化最佳实践](explanation/benchmark-interpretation.md)

---

**最后更新**: 2026-04-26  
**版本**: Onion Core v0.9.1+
