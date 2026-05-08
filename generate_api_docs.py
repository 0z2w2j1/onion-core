"""
批量生成 mkdocstrings API Reference 文档（合并版）
"""

from pathlib import Path

# 按类别合并的模块映射
categories = {
    "core": {
        "output": "api/core.md",
        "title": "核心模块 API 参考",
        "modules": [
            ("Pipeline", "onion_core.pipeline"),
            ("Models", "onion_core.models"),
            ("Config", "onion_core.config"),
            ("Error Codes", "onion_core.error_codes"),
            ("Base Middleware", "onion_core.base"),
            ("LLM Provider", "onion_core.provider"),
        ],
    },
    "middlewares": {
        "output": "api/middlewares.md",
        "title": "中间件 API 参考",
        "modules": [
            ("Safety Guardrail", "onion_core.middlewares.safety"),
            ("Context Window", "onion_core.middlewares.context"),
            ("Observability", "onion_core.middlewares.observability"),
            ("Rate Limit", "onion_core.middlewares.ratelimit"),
            ("Response Cache", "onion_core.middlewares.cache"),
            ("Circuit Breaker", "onion_core.circuit_breaker"),
            ("Distributed Cache", "onion_core.middlewares.distributed_cache"),
            ("Distributed Circuit Breaker", "onion_core.middlewares.distributed_circuit_breaker"),
            ("Distributed Rate Limit", "onion_core.middlewares.distributed_ratelimit"),
        ],
    },
    "providers": {
        "output": "api/providers.md",
        "title": "Provider API 参考",
        "modules": [
            ("OpenAI", "onion_core.providers.openai"),
            ("Anthropic", "onion_core.providers.anthropic"),
            ("国产 AI", "onion_core.providers.domestic"),
            ("本地模型", "onion_core.providers.local"),
        ],
    },
    "agent": {
        "output": "api/agent.md",
        "title": "Agent API 参考",
        "modules": [
            ("Agent Runtime", "onion_core.agent"),
            ("Tool Registry", "onion_core.tools"),
        ],
    },
    "observability": {
        "output": "api/observability.md",
        "title": "可观测性 API 参考",
        "modules": [
            ("结构化日志", "onion_core.observability.logging"),
            ("Prometheus 指标", "onion_core.observability.metrics"),
            ("OpenTelemetry 追踪", "onion_core.observability.tracing"),
        ],
    },
    "infrastructure": {
        "output": "api/infrastructure.md",
        "title": "基础设施 API 参考",
        "modules": [
            ("Health Server", "onion_core.health_server"),
            ("Manager", "onion_core.manager"),
        ],
    },
}


def generate_api_doc(output_file: str, title: str, modules: list[tuple[str, str]]) -> None:
    """生成按类别合并的 API 文档"""
    lines = [f"# {title}", ""]

    for section_name, module_path in modules:
        lines.append(f"## {section_name}")
        lines.append("")
        lines.append(f"::: {module_path}")
        lines.append("    options:")
        lines.append("      show_root_heading: false")
        lines.append("      show_source: true")
        lines.append("      members_order: source")
        lines.append("      group_by_category: true")
        lines.append("")

    output_path = Path("docs") / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Generated: {output_file} ({len(modules)} 个模块)")


def main() -> None:
    print("生成 API Reference 文档...\n")

    total_modules = 0
    for category, info in categories.items():
        try:
            generate_api_doc(info["output"], info["title"], info["modules"])
            total_modules += len(info["modules"])
        except Exception as e:
            print(f"FAILED to generate {info['output']}: {e}")

    print(f"\n共生成 {len(categories)} 个文档文件，覆盖 {total_modules} 个模块！")
    print("\n下一步：运行 'mkdocs build' 生成文档站点。")


if __name__ == "__main__":
    main()
