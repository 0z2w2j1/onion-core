# Onion Core 参考手册

参考手册提供**准确、完整的技术信息**。面向需要在开发过程中查阅细节的开发者。

## API 参考（自动生成）

完整的 API 文档由源码 docstring 自动生成，请查看以下分类：

- [核心模块](../api/core.md) — Pipeline、Models、Config、Error Codes、Base、Provider
- [中间件](../api/middlewares.md) — Safety、Context、RateLimit、Cache、Observability、CircuitBreaker
- [Provider](../api/providers.md) — OpenAI、Anthropic、DeepSeek、智谱、Kimi、通义千问、Ollama
- [Agent](../api/agent.md) — AgentRuntime、AgentLoop、ToolRegistry
- [可观测性](../api/observability.md) — 日志、指标、追踪
- [基础设施](../api/infrastructure.md) — Health Server、Manager、Circuit Breaker

## 策略与约定

- [API 稳定性政策](api-stability.md) — 哪些 API 可以安全依赖
- [Provider 契约](provider-contract.md) — 实现自定义 Provider 需要满足的接口

## 错误码速查

| 范围 | 类别 | 示例 |
|------|------|------|
| 100-199 | 安全错误 | `ONI-S100`: 关键词拦截 |
| 200-299 | 限流错误 | `ONI-R200`: 超出速率限制 |
| 300-399 | 熔断器错误 | `ONI-C300`: 熔断器开启 |
| 400-499 | Provider 错误 | `ONI-P400`: 认证失败 |
| 500-599 | 中间件错误 | `ONI-M500`: 请求处理失败 |
| 600-699 | 验证错误 | `ONI-V600`: 配置无效 |
| 700-799 | 超时错误 | `ONI-T700`: Provider 超时 |
| 800-899 | Fallback 错误 | `ONI-F800`: 触发降级 |
| 900-999 | 内部错误 | `ONI-I900`: 未预期异常 |

完整错误码详情请查看 [API 参考 → Error Codes](../api/core.md)。

## 配置加载方式

```python
# 1. 代码中直接配置
config = OnionConfig()
config.safety.enable_pii_masking = True
config.pipeline.max_retries = 3

# 2. 从环境变量加载
config = OnionConfig.from_env()  # 读取 ONION__*

# 3. 从 JSON/YAML 文件加载
config = OnionConfig.from_file("onion.json")
```

## 下一步

- 查看 **[操作指南](../how-to-guides/README.md)** 学习如何使用这些 API
- 阅读 **[背景解释](../explanation/README.md)** 理解设计原理
- 浏览 **[教程](../tutorials/README.md)** 快速上手
