# 分布式系统一致性

本文解释 Onion Core 分布式中间件的一致性模型、TOCTOU 问题以及设计权衡。

## 什么是分布式中间件？

Onion Core 提供了三个基于 Redis 的分布式中间件：

1. **DistributedRateLimitMiddleware** - 分布式限流
2. **DistributedCacheMiddleware** - 分布式缓存
3. **DistributedCircuitBreakerMiddleware** - 分布式熔断器

这些中间件允许多个 Onion Core 实例共享状态，实现集群级别的限流、缓存和熔断。

---

## 一致性模型：最终一致性

### 强一致性 vs 最终一致性

| 特性 | 强一致性 | 最终一致性 |
|------|---------|-----------|
| **定义** | 所有节点立即看到相同数据 | 经过一段时间后，所有节点看到相同数据 |
| **优点** | 数据准确，无竞态条件 | 高性能，高可用 |
| **缺点** | 延迟高，可用性低 | 可能存在短暂不一致 |
| **示例** | 银行转账 | DNS 缓存、CDN |

**Onion Core 选择最终一致性**，原因：
- ✅ **性能优先**：AI 应用对延迟敏感
- ✅ **可用性优先**：宁可短暂不一致，也不能拒绝服务
- ✅ **容错性强**：Redis 故障时仍可降级运行

---

## TOCTOU 竞态条件

### 什么是 TOCTOU？

**TOCTOU** = Time Of Check to Time Of Use（检查到使用的时间差）

这是一个经典的竞态条件问题：

```
时间线：
T1: 线程 A 检查熔断器状态 → CLOSED
T2: 线程 B 检查熔断器状态 → CLOSED
T3: 线程 A 调用 Provider → 失败
T4: 线程 A 记录失败 → 熔断器变为 OPEN
T5: 线程 B 调用 Provider → 仍然执行（因为 T2 时是 CLOSED）❌
```

在 T2 和 T5 之间，熔断器状态已经改变，但线程 B 不知道。

---

### TOCTOU 在分布式熔断器中的体现

#### 场景：多实例同时检测到失败

```
实例 1:                          实例 2:
  │                                │
  ├─ 检查熔断器 (CLOSED)           │
  │                                ├─ 检查熔断器 (CLOSED)
  ├─ 调用 Provider                 │
  │                                ├─ 调用 Provider
  ├─ 失败                          │
  ├─ 记录失败 (failure_count=4)    │                                ├─ 失败
  │                                ├─ 记录失败 (failure_count=5) → OPEN ❌
  ├─ 记录失败 (failure_count=5) → OPEN
  │
  └─ 两个实例都认为自己是"最后一个"
```

**问题**：
- 两个实例可能同时触发熔断
- 或者一个实例触发后，另一个实例仍在发送请求

---

### 为什么不用分布式锁解决？

理论上可以用 Redis 分布式锁保证原子性：

```python
# 伪代码
lock = redis.lock(f"circuit_breaker:{provider_id}")
with lock:
    state = get_circuit_state()
    if state == CLOSED:
        call_provider()
        if failed:
            record_failure()
```

**但这样做的问题**：
1. ❌ **性能开销大**：每次请求都要获取/释放锁
2. ❌ **单点故障**：锁服务不可用时整个系统瘫痪
3. ❌ **死锁风险**：如果持有锁的实例崩溃，其他实例等待超时

---

## Onion Core 的设计权衡

### 接受 TOCTOU，优先可用性

Onion Core **故意不解决** TOCTOU 问题，原因：

#### 1. 影响有限

```
假设：
- 熔断阈值 = 5 次连续失败
- TOCTOU 窗口 = 10ms（Redis 操作耗时）
- QPS = 1000

最坏情况：
- 窗口内额外请求数 = 1000 × 0.01 = 10 次
- 相对于总流量，影响 < 1%
```

**结论**：TOCTOU 导致的额外失败请求占比极小，可接受。

---

#### 2. 自愈能力强

即使出现 TOCTOU 问题：
- 熔断器会在 `recovery_timeout` 后自动恢复到 HALF_OPEN
- 失败的请求会快速切换到 Fallback Provider
- 用户感知到的只是少量额外错误

---

#### 3. 简化架构

不使用分布式锁带来以下好处：
- ✅ **代码简单**：无需处理锁超时、重试、死锁
- ✅ **性能高**：无锁竞争，Redis 操作更快
- ✅ **容错强**：Redis 短暂故障不影响核心功能

---

## 分布式缓存的一致性问题

### 缓存失效延迟

#### 场景：多实例缓存不同步

```
时间线：
T1: 实例 A 缓存用户查询结果（TTL=3600s）
T2: 用户数据在数据库中更新
T3: 实例 B 未命中缓存，从数据库读取最新数据并缓存
T4: 实例 A 仍返回旧缓存数据（直到 TTL 过期）❌
```

**问题**：不同实例可能返回不一致的数据。

---

### 为什么不主动失效？

可以设计主动失效机制：

```python
# 伪代码
async def invalidate_cache(key: str):
    # 通知所有实例失效缓存
    await redis.publish("cache_invalidation", key)
    
    # 每个实例订阅该频道
    async for message in redis.subscribe("cache_invalidation"):
        local_cache.delete(message.key)
```

**但这样做的问题**：
1. ❌ **复杂性高**：需要维护发布/订阅系统
2. ❌ **可靠性低**：消息可能丢失，导致缓存不一致
3. ❌ **扩展性差**：实例数量增加时，消息风暴

---

### Onion Core 的策略：TTL + 惰性失效

```python
class DistributedCacheMiddleware:
    def __init__(self, ttl: int = 3600):
        self.ttl = ttl  # 默认 1 小时
    
    async def process_request(self, context):
        cache_key = self._generate_key(context)
        
        # 尝试从 Redis 获取缓存
        cached = await redis.get(cache_key)
        if cached:
            return self._deserialize(cached)
        
        # 未命中，继续执行
        return context
```

**优势**：
- ✅ **简单可靠**：无需复杂的失效协议
- ✅ **最终一致**：TTL 过期后所有实例看到新数据
- ✅ **可配置**：根据业务需求调整 TTL

**权衡**：
- ⚠️ 最多 `ttl` 秒的不一致窗口
- ⚠️ 不适合强一致性要求的场景（如金融交易）

---

## 分布式限流的原子性保证

### 使用 Lua 脚本保证原子性

与熔断器和缓存不同，**分布式限流必须保证原子性**，否则会导致限流失效。

```lua
-- Redis Lua 脚本
local key = KEYS[1]
local max_requests = tonumber(ARGV[1])
local window = tonumber(ARGV[2])

local current = redis.call('GET', key)
if not current then
    redis.call('SET', key, 1, 'EX', window)
    return 1
end

if tonumber(current) >= max_requests then
    return 0  -- 限流
end

redis.call('INCR', key)
return 1  -- 允许通过
```

**为什么 Lua 脚本能保证原子性？**
- Redis 单线程执行 Lua 脚本
- 脚本执行期间不会被其他命令中断
- 避免了 CHECK-THEN-ACT 的竞态条件

---

### Python 端调用

```python
class DistributedRateLimitMiddleware:
    LUA_SCRIPT = """
    local key = KEYS[1]
    local max_requests = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    
    local current = redis.call('GET', key)
    if not current then
        redis.call('SET', key, 1, 'EX', window)
        return 1
    end
    
    if tonumber(current) >= max_requests then
        return 0
    end
    
    redis.call('INCR', key)
    return 1
    """
    
    async def process_request(self, context):
        allowed = await redis.eval(
            self.LUA_SCRIPT,
            keys=[f"ratelimit:{context.session_id}"],
            args=[self.max_requests, self.window_seconds]
        )
        
        if not allowed:
            raise RateLimitExceeded(...)
        
        return context
```

---

## 分层限流的竞态条件

### 问题：普通请求 vs 工具调用

```python
rate_limit_mw = DistributedRateLimitMiddleware(
    max_requests=60,         # 普通请求：60次/分钟
    max_tool_calls=20,       # 工具调用：20次/分钟
)
```

**潜在竞态**：
```
T1: 检查普通请求配额 → 剩余 1 次
T2: 检查工具调用配额 → 剩余 1 次
T3: 发送既是普通请求又是工具调用的消息
T4: 普通请求配额减为 0
T5: 工具调用配额减为 0
T6: 下一个请求被错误地允许通过 ❌
```

---

### 解决方案：独立 Key + 原子检查

```lua
-- 分别维护两个计数器
local request_key = KEYS[1]
local tool_key = KEYS[2]

local request_remaining = check_and_decr(request_key, ARGV[1], ARGV[2])
local tool_remaining = check_and_decr(tool_key, ARGV[3], ARGV[4])

if request_remaining < 0 or tool_remaining < 0 then
    return 0  -- 限流
end

return 1  -- 允许
```

**关键**：在一个 Lua 脚本中同时检查两个配额，保证原子性。

---

## 故障降级策略

### Redis 不可用时的行为

```python
class DistributedRateLimitMiddleware:
    def __init__(self, fallback_allow: bool = False):
        self.fallback_allow = fallback_allow
    
    async def process_request(self, context):
        try:
            allowed = await redis.eval(...)
            return context if allowed else raise_rate_limit()
        
        except redis.ConnectionError:
            # Redis 故障
            if self.fallback_allow:
                logger.warning("Redis unavailable, allowing request")
                return context  # 允许通过
            else:
                logger.error("Redis unavailable, blocking request")
                raise ServiceUnavailableError()
```

**两种策略对比**：

| 策略 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| `fallback_allow=True` | 高可用，不拒绝服务 | 可能超限 | 非关键业务 |
| `fallback_allow=False` | 严格限流 | Redis 故障时全部拒绝 | 关键业务 |

---

## 最佳实践

### 1. 合理设置 TTL

```python
# ❌ TTL 太长：数据不一致窗口大
cache_mw = DistributedCacheMiddleware(ttl=86400)  # 24 小时

# ✅ TTL 适中：平衡一致性和性能
cache_mw = DistributedCacheMiddleware(ttl=3600)   # 1 小时

# ✅ 短 TTL + 高频刷新：近似实时
cache_mw = DistributedCacheMiddleware(ttl=60)     # 1 分钟
```

---

### 2. 监控 Redis 延迟

```python
import time

start = time.time()
await redis.ping()
latency = time.time() - start

if latency > 0.1:  # 超过 100ms
    logger.warning(f"High Redis latency: {latency:.2f}s")
```

**高延迟会增加 TOCTOU 窗口**，需及时告警。

---

### 3. 使用连接池

```python
import redis.asyncio as redis

pool = redis.ConnectionPool.from_url(
    "redis://localhost:6379",
    max_connections=20,          # 连接池大小
    socket_connect_timeout=5.0,  # 连接超时
    socket_timeout=5.0,          # 操作超时
)

client = redis.Redis(connection_pool=pool)
```

---

### 4. 定期清理过期 Key

```bash
# Redis 会自动清理过期 Key，但可以手动优化
redis-cli --scan --pattern "onion:*" | xargs redis-cli DEL
```

---

## 总结

Onion Core 的分布式中间件采用**最终一致性**模型：

| 中间件 | 一致性要求 | 实现方式 | TOCTOU 风险 |
|--------|-----------|---------|------------|
| **分布式限流** | 强一致 | Lua 脚本原子执行 | ❌ 无 |
| **分布式缓存** | 最终一致 | TTL 过期 | ⚠️ 有（可接受） |
| **分布式熔断器** | 最终一致 | 无锁设计 | ⚠️ 有（影响小） |

**设计哲学**：
- ✅ **性能优先**：避免分布式锁带来的延迟
- ✅ **可用性优先**：Redis 故障时可降级运行
- ✅ **简单可靠**：减少复杂的状态同步逻辑

对于需要强一致性的场景（如金融交易），建议在应用层实现额外的幂等性检查和补偿机制。

---

## 延伸阅读

- [操作指南: 配置 Redis 分布式限流](../how-to-guides/configure-distributed-ratelimit.md)
- [背景解释: Pipeline 调度引擎](pipeline-scheduling.md)
- [API 参考: DistributedRateLimitMiddleware](../reference/middlewares.md#distributedratelimitmiddleware)
