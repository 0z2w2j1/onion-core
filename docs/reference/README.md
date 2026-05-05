# Onion Core Reference

参考手册提供**准确、完整的技术信息**。它们面向需要在开发过程中查阅细节的开发者。

## 📚 API 参考

### 核心类

- [Pipeline](pipeline.md) - 中央调度引擎（完整 API 文档）
- [AgentContext](../api/models.md) - 请求上下文
- [BaseMiddleware](middlewares.md#basemiddleware) - 中间件基类
- [LLMProvider](../api/provider.md) - Provider 抽象接口

### 中间件

- [所有中间件 API](middlewares.md) - 完整的中间件参考
  - [SafetyGuardrailMiddleware](middlewares.md#safetyguardrailmiddleware) - 安全护栏
  - [ContextWindowMiddleware](middlewares.md#contextwindowmiddleware) - 上下文窗口管理
  - [ObservabilityMiddleware](middlewares.md#observabilitymiddleware) - 可观测性
  - [DistributedRateLimitMiddleware](middlewares.md#distributedratelimitmiddleware) - 分布式限流
  - [DistributedCacheMiddleware](middlewares.md#distributedcachemiddleware) - 分布式缓存
  - [DistributedCircuitBreakerMiddleware](middlewares.md#distributedcircuitbreakermiddleware) - 分布式熔断器

### Provider

- [OpenAIProvider](../api/providers/openai.md) - OpenAI API
- [AnthropicProvider](../api/providers/anthropic.md) - Anthropic API
- [DeepSeekProvider](../api/providers/domestic.md) - DeepSeek API
- [ZhipuAIProvider](../api/providers/domestic.md) - 智谱 GLM
- [MoonshotProvider](../api/providers/domestic.md) - Kimi
- [DashScopeProvider](../api/providers/domestic.md) - 通义千问
- [OllamaProvider](../api/providers/local.md) - Ollama 本地模型
- [LMStudioProvider](../api/providers/local.md) - LM Studio

### Agent

- [AgentRuntime](../api/agent.md) - Agent 运行时
- [AgentLoop](../api/agent.md) - ReAct 循环引擎
- [ToolRegistry](../api/tools.md) - 工具注册表

## 🔢 错误码

完整的错误码列表和重试策略，请查看 [错误码参考](../api/error_codes.md)。

### 错误码分类

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

## ⚙️ 配置选项

所有配置字段说明，请查看 [配置参考](../api/config.md)。

### 配置加载方式

```python
# 1. 代码中直接配置（子配置作为 OnionConfig 的嵌套字段）
config = OnionConfig()
config.safety.enable_pii_masking = True
config.pipeline.max_retries = 3

# 2. 从环境变量加载
config = OnionConfig.from_env()  # 读取 ONION__*

# 3. 从 JSON/YAML 文件加载
config = OnionConfig.from_file("onion.json")
```

## 📖 下一步

- 查看 **[操作指南](../how-to-guides/README.md)** 学习如何使用这些 API
- 阅读 **[背景解释](../explanation/README.md)** 理解设计原理
- 浏览 **[教程](../tutorials/README.md)** 快速上手

---

> **注意**: 本文档正在建设中。完整的 API 参考将通过自动化工具从代码注释生成。如需立即查阅详细签名，请参考源代码或 IDE 的类型提示。
