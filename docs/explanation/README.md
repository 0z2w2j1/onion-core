# Onion Core Explanation

解释性文档帮助你**理解** Onion Core 的设计原理、架构决策和背景知识。它们面向需要深入理解系统的开发者。

## 架构与设计

- [洋葱模型设计哲学](onion-model-philosophy.md) - 为什么选择洋葱架构而非传统中间件链 ✅
- [Pipeline 调度引擎详解](pipeline-scheduling.md) - 请求如何在中间件间流转 ✅ **新增**
- [状态机与 Agent 循环](agent-state-machine.md) - ReAct 模式的实现细节

## 核心概念

- [错误码系统设计](error-code-system.md) - 统一错误分类与重试策略 ✅ **新增**
- [上下文管理权衡](context-management-tradeoffs.md) - 内存 vs 精度 vs 性能
- [异步编程模型](async-programming-model.md) - asyncio 最佳实践与陷阱

## 高级主题

- [分布式系统一致性](distributed-consistency.md) - TOCTOU 问题与最终一致性 ✅ **新增**
- [熔断器状态转换](circuit-breaker-transitions.md) - CLOSED/OPEN/HALF_OPEN 的生命周期
- [流式 PII 脱敏算法](streaming-pii-algorithm.md) - 滑动窗口与超时刷新机制

## 性能与优化

- [性能基准测试解读](benchmark-interpretation.md) - 如何阅读和理解压测数据
- [内存管理与 GC 优化](memory-management.md) - 防止 OOM 的策略
- [线程池调优指南](threadpool-tuning.md) - tiktoken 异步计算的权衡
