"""向后兼容别名：旧 onion_core.manager 迁移到 onion_core.pipeline。"""
from __future__ import annotations

from onion_core.pipeline import Pipeline as MiddlewareManager  # noqa: F401
