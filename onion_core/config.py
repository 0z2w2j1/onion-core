"""
Onion Core - 配置系统

支持三种配置来源（优先级从高到低）：
  1. 代码直接传入
  2. 环境变量（ONION_ 前缀，由 Pydantic BaseSettings 原生处理）
  3. JSON / YAML 配置文件

环境变量命名规则（全大写，双下划线分隔嵌套）：
  ONION__PIPELINE__MAX_RETRIES=3
  ONION__SAFETY__ENABLE_PII_MASKING=false
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("onion_core.config")


class SafetyConfig(BaseModel):
    blocked_keywords: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    enable_pii_masking: bool = True


class ContextWindowConfig(BaseModel):
    max_tokens: int = 4000
    keep_rounds: int = 2
    encoding_name: str = "cl100k_base"


class ObservabilityConfig(BaseModel):
    log_level: str = "INFO"
    log_tool_args: bool = True


class PipelineConfig(BaseModel):
    middleware_timeout: float | None = None
    max_retries: int = 0
    provider_timeout: float | None = None
    enable_circuit_breaker: bool = True
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 30.0


class OnionConfig(BaseSettings):
    """
    Onion Core 全局配置。

    使用 pydantic-settings 自动从环境变量加载配置。
    支持 ONION__ 前缀。
    """

    model_config = SettingsConfigDict(
        env_prefix="ONION__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    context_window: ContextWindowConfig = Field(default_factory=ContextWindowConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> OnionConfig:
        """从 JSON/YAML 文件加载配置，环境变量仍可覆盖文件值。"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        if p.stat().st_size > 1024 * 1024:
            raise ValueError(f"Config file too large (max 1 MB): {p}")

        suffix = p.suffix.lower()
        if suffix == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
        elif suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
            except ImportError as err:
                raise ImportError("pip install pyyaml to use YAML config files") from err
        else:
            raise ValueError(f"Unsupported config format: {suffix}")

        logger.info("Config loaded from: %s", p)
        return cls.model_validate(data)

    @classmethod
    def from_env(cls) -> OnionConfig:
        """纯从环境变量加载配置。"""
        return cls()

    def get(self, key: str, default: Any = None) -> Any:
        """点分路径访问配置值，如 cfg.get('context_window.max_tokens')。"""
        parts = key.split(".", 1)
        section = getattr(self, parts[0], None)
        if section is None:
            return default
        if len(parts) == 1:
            return section
        return getattr(section, parts[1].replace(".", "_"), default)

    def to_context_config(self) -> dict[str, Any]:
        """序列化为 AgentContext.config 格式。"""
        return {"onion": self.model_dump()}
