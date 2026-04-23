"""
Onion Core - 结构化日志

提供 JSON 格式的结构化日志 formatter，可直接接入 ELK / Loki / CloudWatch。

用法：
    from onion_core.observability.logging import configure_logging
    configure_logging(level="INFO", json_format=True)

    # 或手动配置
    import logging
    from onion_core.observability.logging import JsonFormatter
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.getLogger("onion_core").addHandler(handler)
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    """
    将日志记录序列化为单行 JSON，适合日志聚合系统消费。

    输出字段：
        timestamp  — ISO 8601 UTC
        level      — DEBUG / INFO / WARNING / ERROR / CRITICAL
        logger     — logger 名称
        message    — 格式化后的消息
        request_id — 从消息前缀 [xxx] 提取（可选）
        exc_info   — 异常堆栈（仅在有异常时出现）
        extra      — LogRecord 上的额外字段
    """

    # 标准 LogRecord 字段，不放入 extra
    _SKIP_ATTRS = frozenset({
        "args", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message",
        "module", "msecs", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "thread",
        "threadName",
    })

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # 从消息前缀 [request_id] 提取 request_id
        msg = record.message
        if msg.startswith("[") and "]" in msg:
            end = msg.index("]")
            payload["request_id"] = msg[1:end]

        # 异常信息
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # 额外字段
        extra = {
            k: v for k, v in record.__dict__.items()
            if k not in self._SKIP_ATTRS and not k.startswith("_")
        }
        if extra:
            payload["extra"] = extra

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    level: str = "INFO",
    json_format: bool = False,
    logger_name: str = "onion_core",
) -> logging.Logger:
    """
    配置 onion_core 日志。

    Args:
        level: 日志级别字符串，如 "DEBUG", "INFO", "WARNING"
        json_format: True 使用 JSON 格式，False 使用人类可读格式
        logger_name: 要配置的 logger 名称

    Returns:
        配置好的 logger 实例
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler()
        if json_format:
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
            ))
        logger.addHandler(handler)

    return logger
