# 如何自定义 PII 脱敏规则

本指南展示如何为 `SafetyGuardrailMiddleware` 添加自定义的 PII（个人身份信息）脱敏规则。

## 前提条件

- 已了解 [构建安全 Agent](../tutorials/02-secure-agent.md) 教程
- 熟悉正则表达式基础

## 默认 PII 规则

Onion Core 内置了以下 PII 规则：

| 类型 | 匹配示例 | 脱敏后 |
|------|---------|--------|
| 手机号 | `13812345678` | `***` |
| 邮箱 | `test@example.com` | `[email]` |
| 身份证 | `110101199001011234` | `***` |
| 银行卡 | `6222021234567890123` | `***` |

## 步骤 1: 创建自定义 PII 规则

使用 `PiiRule` 类定义新规则：

```python
from onion_core.middlewares.safety import PiiRule
import re

# 示例 1: 脱敏 IP 地址
ip_rule = PiiRule(
    name="ipv4_address",
    pattern=re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    replacement="[IP]",
    description="IPv4 地址"
)

# 示例 2: 脱敏信用卡号（国际格式）
credit_card_rule = PiiRule(
    name="credit_card",
    pattern=re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
    replacement="[CARD]",
    description="信用卡号"
)

# 示例 3: 脱敏姓名（中文，2-4 个字）
chinese_name_rule = PiiRule(
    name="chinese_name",
    pattern=re.compile(r"[\u4e00-\u9fa5]{2,4}"),
    replacement="[NAME]",
    description="中文姓名"
)
```

### PiiRule 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 规则唯一标识符 |
| `pattern` | `re.Pattern` | 编译后的正则表达式 |
| `replacement` | `str` | 替换字符串 |
| `description` | `str \| None` | 规则描述（可选） |

---

## 步骤 2: 添加到中间件

```python
from onion_core import Pipeline, EchoProvider
from onion_core.middlewares import SafetyGuardrailMiddleware

async def main():
    # 创建安全中间件
    safety_mw = SafetyGuardrailMiddleware(
        enable_builtin_pii=True,  # 保留内置规则
    )
    
    # 添加自定义规则
    safety_mw.add_pii_rule(ip_rule)
    safety_mw.add_pii_rule(credit_card_rule)
    
    # 创建 Pipeline
    async with Pipeline(provider=EchoProvider()) as p:
        p.add_middleware(safety_mw)
        
        # 测试
        from onion_core import AgentContext, Message
        
        ctx = AgentContext(messages=[
            Message(role="user", content="服务器 IP 是 192.168.1.100")
        ])
        
        response = await p.run(ctx)
        print(response.content)
        # 输出: Echo: 服务器 IP 是 [IP]

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 步骤 3: 批量添加规则

如果需要添加多个规则，可以使用循环：

```python
custom_rules = [
    PiiRule(
        name="phone_cn",
        pattern=re.compile(r"1[3-9]\d{9}"),
        replacement="[PHONE]",
    ),
    PiiRule(
        name="email",
        pattern=re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        replacement="[EMAIL]",
    ),
    PiiRule(
        name="id_card",
        pattern=re.compile(r"\d{17}[\dXx]"),
        replacement="[ID]",
    ),
]

safety_mw = SafetyGuardrailMiddleware(enable_builtin_pii=False)  # 禁用内置规则
for rule in custom_rules:
    safety_mw.add_pii_rule(rule)
```

---

## 高级用法

### 1. 条件脱敏

根据上下文决定是否脱敏：

```python
from onion_core.middlewares import BaseMiddleware

class ConditionalPiiMiddleware(BaseMiddleware):
    """仅在特定会话中脱敏"""
    
    def __init__(self, sensitive_sessions: set[str]):
        super().__init__(name="conditional_pii", priority=199)
        self.sensitive_sessions = sensitive_sessions
    
    async def process_response(self, context, response):
        if context.session_id in self.sensitive_sessions:
            # 执行脱敏逻辑
            response.content = self._mask_pii(response.content)
        return response
    
    def _mask_pii(self, text: str) -> str:
        # 自定义脱敏逻辑
        import re
        return re.sub(r"1[3-9]\d{9}", "***", text)
```

---

### 2. 动态规则加载

从配置文件或数据库加载规则：

```python
import json

def load_pii_rules_from_file(filepath: str) -> list[PiiRule]:
    """从 JSON 文件加载 PII 规则"""
    with open(filepath, 'r', encoding='utf-8') as f:
        rules_data = json.load(f)
    
    rules = []
    for item in rules_data:
        rule = PiiRule(
            name=item["name"],
            pattern=re.compile(item["pattern"]),
            replacement=item.get("replacement", "***"),
            description=item.get("description"),
        )
        rules.append(rule)
    
    return rules

# 使用
rules = load_pii_rules_from_file("pii_rules.json")
safety_mw = SafetyGuardrailMiddleware()
for rule in rules:
    safety_mw.add_pii_rule(rule)
```

**pii_rules.json 示例**:
```json
[
  {
    "name": "us_phone",
    "pattern": "\\b\\d{3}-\\d{3}-\\d{4}\\b",
    "replacement": "[US-PHONE]",
    "description": "美国电话号码"
  },
  {
    "name": "ssn",
    "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b",
    "replacement": "[SSN]",
    "description": "美国社会安全号"
  }
]
```

---

### 3. 流式响应中的 PII 脱敏

流式模式下，PII 可能被分割到多个 chunk 中。`SafetyGuardrailMiddleware` 会自动缓冲并处理：

```python
async def test_streaming_pii():
    async with Pipeline(provider=OpenAIProvider()) as p:
        p.add_middleware(SafetyGuardrailMiddleware())
        
        ctx = AgentContext(messages=[
            Message(role="user", content="我的电话是多少？")
        ])
        
        # 流式响应会自动脱敏
        async for chunk in p.stream(ctx):
            if chunk.delta:
                print(chunk.delta, end="", flush=True)
                # 即使 PII 跨多个 chunk，也会被正确脱敏
```

**注意**: 流式脱敏会引入最多 **2 秒** 或 **50 个字符** 的延迟，以确保完整性。

---

## 调试与验证

### 查看已注册的规则

```python
safety_mw = SafetyGuardrailMiddleware()
print(f"内置规则数: {len(safety_mw.builtin_rules)}")
print(f"自定义规则数: {len(safety_mw.custom_rules)}")

for rule in safety_mw.all_rules:
    print(f"  - {rule.name}: {rule.pattern.pattern}")
```

### 测试脱敏效果

```python
def test_pii_masking():
    safety_mw = SafetyGuardrailMiddleware()
    
    test_cases = [
        ("我的电话是 13812345678", "我的电话是 ***"),
        ("邮箱 test@example.com", "邮箱 [email]"),
        ("IP 地址 192.168.1.1", "IP 地址 [IP]"),
    ]
    
    for input_text, expected in test_cases:
        result = safety_mw._mask_pii(input_text)
        assert result == expected, f"Expected {expected}, got {result}"
        print(f"✅ {input_text[:20]}... → {result}")

test_pii_masking()
```

---

## 常见问题

### Q: 如何禁用某个内置规则？

A: 目前无法单独禁用内置规则。如需完全自定义，设置 `enable_builtin_pii=False` 然后添加所有需要的规则。

```python
safety_mw = SafetyGuardrailMiddleware(enable_builtin_pii=False)
# 手动添加所需规则
safety_mw.add_pii_rule(phone_rule)
safety_mw.add_pii_rule(email_rule)
```

---

### Q: 正则表达式性能如何优化？

A: 
1. 使用 `re.compile()` 预编译正则
2. 避免使用贪婪匹配 `.*`，改用 `.*?` 或具体字符类
3. 使用锚点 `^` `$` `\b` 缩小匹配范围

```python
# ❌ 慢
pattern = re.compile(r".*1\d{9}.*")

# ✅ 快
pattern = re.compile(r"\b1[3-9]\d{9}\b")
```

---

### Q: 如何处理多语言 PII？

A: 为每种语言创建独立规则：

```python
# 中文姓名
cn_name = PiiRule(
    name="cn_name",
    pattern=re.compile(r"[\u4e00-\u9fa5]{2,4}"),
    replacement="[中文姓名]",
)

# 英文姓名（首字母大写 + 空格）
en_name = PiiRule(
    name="en_name",
    pattern=re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"),
    replacement="[English Name]",
)

safety_mw.add_pii_rule(cn_name)
safety_mw.add_pii_rule(en_name)
```

---

## 最佳实践

1. ✅ **优先使用内置规则**：覆盖常见 PII 类型
2. ✅ **规则命名清晰**：使用下划线分隔，如 `us_phone`、`cn_id_card`
3. ✅ **测试边界情况**：确保正则不会误匹配正常文本
4. ✅ **记录脱敏日志**：在 `on_error` 中记录被脱敏的内容类型（不记录具体内容）
5. ❌ **避免过度脱敏**：不要脱敏非敏感信息（如产品编号、订单号）

---

## 下一步

- 查看 **[API 参考: SafetyGuardrailMiddleware](../reference/middlewares.md#safetyguardrailmiddleware)** 了解完整接口
- 阅读 **[背景解释: 流式 PII 脱敏算法](../explanation/streaming-pii-algorithm.md)** 理解实现原理
- 学习 **[操作指南: 添加自定义关键词拦截](custom-blocked-keywords.md)** 增强安全防护
