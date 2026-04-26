## 迁移说明：从 AgentLoop 到 AgentRuntime

### 1. 核心循环映射

**旧代码 (onion_core/agent.py — AgentLoop)**
```python
class AgentLoop:
    async def run(self, context: AgentContext) -> LLMResponse:
        for turn in range(self.max_turns):       # 硬编码循环
            response = await self.pipeline.run(context)
            if not response.has_tool_calls:       # 隐式决策
                return response
            for tool_call in response.tool_calls:
                result = self.registry.execute(tool_call, context)
                context.messages.append(result.to_message())
        raise AgentLoopError("max_turns exceeded")
```

**新代码 (src/core/agent.py — AgentRuntime)**
```python
class AgentRuntime:
    async def run(self, user_message: str, state=None) -> AgentState:
        while state.steps < self._config.max_steps:  # 显式边界
            state.increment_step()
            decision = await self._planner.decide(state, llm_response)  # 显式决策
            if decision.action_type == ActionType.FINISH:
                self._fsm.transition_to(AgentStatus.FINISHED)  # FSM 控制
                break
            if decision.action_type == ActionType.ACT:
                results = await self._executor.execute_all(tool_calls)  # 并发执行
```

**关键变化：**
- `for turn in range()` → `while state.steps < max_steps` + 显式 `Planner` 决策
- 工具串行执行 → `asyncio.gather` 并发执行 (Semaphore 限制并发数 5)
- 异常抛出终止 → 状态机 `FINISHED`/`ERROR` 状态终结

### 2. 状态管理映射

**旧：** `context.metadata: dict[str, Any]` — 无类型安全的字典携带状态
**新：** `AgentState(BaseModel)` — Pydantic 强类型，字段包括：
- `run_id`, `session_id` — 可追溯 ID
- `status: AgentStatus` — 枚举状态
- `steps_history: list[StepRecord]` — 每步完整记录
- `cumulative_usage: UsageStats` — 累计 Token 消耗

**旧：** 隐式状态传递，中间件通过 `_` 前缀的 metadata key 通信
**新：** 显式 `StateMachine` 控制允许的转换路径：

```
IDLE → THINKING ⇄ ACTING → FINISHED
                            ↘ ERROR → CANCELLED
```

### 3. 工具系统映射

**旧：** `ToolRegistry` 基于函数 + 自动 JSON Schema 生成
```python
@registry.register
def search(query: str) -> dict: ...
```

**新：** `BaseTool` 抽象类，强制 `input_schema: Type[BaseModel]`
```python
class SearchTool(BaseTool):
    name = "search"
    description = "Search the web"
    input_schema = SearchInput  # Pydantic Model

    async def execute(self, query: str) -> dict: ...
```

**关键变化：**
- 字符串解析 → Pydantic `validate_args()` 执行前校验
- 无重试 → `tenacity` 指数退避重试 (默认 3 次)
- 无超时 → `asyncio.wait_for(timeout)` 可配置超时
- 单次执行 → `execute_all()` 并发批量执行

### 4. LLM 客户端映射

**旧：** 依赖 `openai` SDK (openai>=1.0)，通过中间商适配
**新：** 直接使用 `httpx.AsyncClient` 单例模式：
- 连接池复用 (`max_keepalive_connections=20`)
- `tenacity` 重试策略 (Rate Limit 429 和 Server Error 5xx)
- 独立于 SDK 的 provider 实现

### 5. 记忆管理映射

**旧：** `ContextWindowMiddleware` 在 Pipeline 中处理截断
**新：** `SlidingWindowMemory` 独立模块：
- `trim()` 基于 Token 估算从后往前保留消息
- 系统消息优先保留
- `trim_with_summary()` 预留 `MemorySummarizer` 接口

### 6. 配置管理映射

**旧：** `pydantic-settings BaseSettings` (OnionConfig)
**新：** `AgentConfig(BaseModel)` 非 Settings 类，通过依赖注入传入：
```python
config = AgentConfig(model="gpt-4", max_steps=10, memory_max_tokens=4000)
runtime = AgentRuntime(config=config, llm_client=client, tool_registry=registry)
```

### 7. 可观测性映射

**旧：** `ObservabilityMiddleware` + `metrics.py` + `tracing.py` 在 Pipeline 中
**新：** Step 级别的结构化日志 + `on_step`/`on_error` 钩子：
```python
runtime.on_step(lambda step: print(f"[{step.trace_id}] {step.action_type}"))
```
每个 Step 自动输出：`trace_id`, `step_count`, `action_type`, `token_usage`, `latency_ms`

### 8. 新依赖

| 库 | 用途 | 旧代码依赖方式 |
|---|---|---|
| `httpx>=0.25` | 异步 HTTP 客户端 | `openai` SDK 内部依赖 |
| `tenacity>=8.0` | LLM/Tool 重试退避 | Pipeline 内手动实现 |
| `pydantic>=2.0` | 数据校验 | 已有 |
| `pydantic-settings>=2.0` | 配置管理 | 已有 |
| `tiktoken>=0.5` | Token 计数 | 已有（可选） |
| `structlog>=24.0` | 结构化日志 | 无（推荐新增） |

### 使用示例

```python
import asyncio
from src import AgentRuntime, AgentConfig, OpenAILLMClient, ToolRegistry, BaseTool
from pydantic import BaseModel

class CalculatorInput(BaseModel):
    expression: str

class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Evaluate a math expression"
    input_schema = CalculatorInput

    async def execute(self, expression: str) -> str:
        return str(eval(expression))

async def main():
    config = AgentConfig(model="gpt-4", max_steps=5, system_prompt="You are helpful.")
    llm = OpenAILLMClient(config)
    registry = ToolRegistry()
    registry.register(CalculatorTool())

    runtime = AgentRuntime(config, llm, registry)

    state = await runtime.run("What is 123 * 456?")

    print(f"Status: {state.status.value}")
    print(f"Steps: {state.steps}")
    print(f"Tokens: {state.cumulative_usage.total_tokens}")

    for step in state.steps_history:
        print(f"  Step {step.step_index}: {step.action_type.value} ({step.duration_ms:.0f}ms)")

asyncio.run(main())
```

### 9. 模块映射表

| 旧模块 (onion_core/) | 新模块 (src/) | 说明 |
|---|---|---|
| `agent.py` (AgentLoop) | `core/agent.py` (AgentRuntime) | 主循环迁移，新增 Planner + StateMachine |
| `models.py` (AgentContext, Message) | `schema/models.py` | 统一 Pydantic 模型层 |
| 无 | `core/state.py` (AgentState, StateMachine) | 新增显式状态管理 |
| 无 | `core/planner.py` (DefaultPlanner) | 新增显式决策引擎 |
| 无 | `core/executor.py` (ToolExecutor) | 新增工具执行器，含超时/重试 |
| `tools.py` (ToolRegistry) | `tools/base.py` + `tools/registry.py` | 拆分抽象基类与注册逻辑 |
| `provider.py` (LLMProvider) | `llm/base.py` (BaseLLMClient) | 移除 openai SDK，改用 httpx |
| `providers/openai.py` | `llm/openai.py` (OpenAILLMClient) | 直接 HTTP 调用 + tenacity 重试 |
| `middlewares/context.py` | `memory/buffer.py` (SlidingWindowMemory) | 独立 Token 感知记忆模块 |
| `config.py` (OnionConfig) | `schema/models.py` (AgentConfig) | 依赖注入替代全局 Settings |
| `pipeline.py` | 已移除 | Pipeline 模式由 Runtime 内部循环替代 |
```
