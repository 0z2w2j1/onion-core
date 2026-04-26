# Onion Core How-to Guides

操作指南帮助你**解决具体问题**。它们假设你已经了解基本概念，专注于完成特定任务。

## 安装与配置

- [如何安装并配置环境变量](install-and-configure.md)
- [如何从配置文件加载设置](load-config-from-file.md)

## 安全与防护

- [如何自定义 PII 脱敏规则](custom-pii-rules.md) ✅ **新增**
- [如何添加自定义关键词拦截](custom-blocked-keywords.md)
- [如何配置流式 PII 脱敏缓冲](streaming-pii-buffer.md)

## Provider 管理

- [如何配置 OpenAI Provider](configure-openai-provider.md)
- [如何接入国内 AI（DeepSeek、智谱、Kimi）](configure-domestic-ai.md)
- [如何使用本地模型（Ollama、LM Studio）](configure-local-models.md)
- [如何设置多 Provider 故障转移](setup-fallback-providers.md) ✅ **新增**

## 性能与扩展

- [如何配置 Redis 分布式限流](configure-distributed-ratelimit.md)
- [如何启用响应缓存](enable-response-cache.md)
- [如何监控 Pipeline 性能](monitor-pipeline-performance.md)

## Agent 开发

- [如何实现工具调用去重](implement-tool-deduplication.md)
- [如何防止 Agent 陷入死循环](prevent-agent-loops.md)
- [如何在 Flask/Django 中使用同步 API](use-sync-api-in-web-frameworks.md) ✅ **新增**

## 故障排查

- [如何调试中间件执行顺序](debug-middleware-order.md)
- [如何解决超时问题](troubleshoot-timeouts.md) ✅ **新增**
- [如何处理熔断器触发](handle-circuit-breaker-trips.md)
