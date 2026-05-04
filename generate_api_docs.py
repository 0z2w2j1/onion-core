"""
批量生成 mkdocstrings API Reference 文档
"""

from pathlib import Path

# 定义需要生成的模块
modules = {
    # Core modules
    "onion_core.config": "api/config.md",
    "onion_core.error_codes": "api/error_codes.md",
    "onion_core.base": "api/base.md",
    "onion_core.provider": "api/provider.md",
    
    # Middlewares
    "onion_core.middlewares.safety": "api/middlewares/safety.md",
    "onion_core.middlewares.context": "api/middlewares/context.md",
    "onion_core.middlewares.observability": "api/middlewares/observability.md",
    "onion_core.middlewares.ratelimit": "api/middlewares/ratelimit.md",
    "onion_core.middlewares.cache": "api/middlewares/cache.md",
    "onion_core.middlewares.circuit_breaker": "api/middlewares/circuit_breaker.md",
    
    # Providers
    "onion_core.providers.openai": "api/providers/openai.md",
    "onion_core.providers.anthropic": "api/providers/anthropic.md",
    "onion_core.providers.domestic": "api/providers/domestic.md",
    "onion_core.providers.local": "api/providers/local.md",
    
    # Agent
    "onion_core.agent": "api/agent.md",
    "onion_core.tools": "api/tools.md",
    
    # Observability
    "onion_core.observability.logging": "api/observability/logging.md",
    "onion_core.observability.metrics": "api/observability/metrics.md",
    "onion_core.observability.tracing": "api/observability/tracing.md",
}

def generate_api_doc(module_path: str, output_file: str):
    """生成单个模块的 API 文档"""
    
    # 提取类名或模块名作为标题
    module_name = module_path.split(".")[-1]
    title = module_name.replace("_", " ").title()
    
    content = f"""# {title} API Reference

::: {module_path}
    options:
      show_root_heading: true
      show_root_full_path: false
      show_source: true
      members_order: source
      group_by_category: true
"""
    
    # 创建目录
    output_path = Path("docs") / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"Generated: {output_file}")

def main():
    print("Generating API Reference documents...\n")
    
    for module_path, output_file in modules.items():
        try:
            generate_api_doc(module_path, output_file)
        except Exception as e:
            print(f"FAILED to generate {output_file}: {e}")
    
    print(f"\nGenerated {len(modules)} API reference documents!")
    print("\nNext step: Run 'mkdocs build' to generate the documentation site.")

if __name__ == "__main__":
    main()
