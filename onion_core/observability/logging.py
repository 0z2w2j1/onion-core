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
from datetime import UTC, datetime
from typing import Any

from ..middlewares.observability import TraceIdFilter


class JsonFormatter(logging.Formatter):
    """
    将日志记录序列化为单行 JSON，适合日志聚合系统消费。

    输出字段：
        timestamp   — ISO 8601 UTC
        level       — DEBUG / INFO / WARNING / ERROR / CRITICAL
        logger      — logger 名称
        message     — 格式化后的消息
        request_id  — 请求 ID（从消息前缀 [xxx] 提取或 extra 传入）
        trace_id    — 分布式追踪 trace_id（从 extra 或 TraceIdFilter）
        span_id     — 分布式追踪 span_id（从 extra）
        error_code  — 错误码（从 extra）
        exc_info    — 异常堆栈（仅在有异常时出现）
        extra       — LogRecord 上的额外字段
    """

    _SKIP_ATTRS = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "trace_id",
            "request_id",
            "span_id",
            "error_code",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # 从消息前缀 [request_id] 提取 request_id
        msg = record.message
        if msg.startswith("[") and "]" in msg:
            end = msg.index("]")
            payload["request_id"] = msg[1:end]

        # trace_id: 优先从 extra，其次从 TraceIdFilter 注入的 record 属性
        trace_id = getattr(record, "trace_id", "")
        if not trace_id:
            trace_id = getattr(record, "extra", {}).get("trace_id", "")
        if trace_id:
            payload["trace_id"] = str(trace_id)

        # span_id
        span_id = getattr(record, "span_id", "")
        if not span_id:
            span_id = getattr(record, "extra", {}).get("span_id", "")
        if span_id:
            payload["span_id"] = str(span_id)

        # request_id from extra (overrides prefix extraction)
        req_id = getattr(record, "request_id", "")
        if not req_id:
            req_id = getattr(record, "extra", {}).get("request_id", "")
        if req_id:
            payload["request_id"] = str(req_id)

        # error_code
        error_code = getattr(record, "error_code", "")
        if not error_code:
            error_code = getattr(record, "extra", {}).get("error_code", "")
        if error_code:
            payload["error_code"] = str(error_code)

        # 异常信息
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
            if record.exc_text:
                payload["exc_text"] = record.exc_text

        # 额外字段
        extra = {
            k: v
            for k, v in record.__dict__.items()
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
        handler.addFilter(TraceIdFilter())
        if json_format:
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
            )
        logger.addHandler(handler)

    return logger


class StructuredLogAdapter:
    """
    结构化日志适配器，自动注入 request_id, trace_id, error_code 等字段。

    用法:
        logger = StructuredLogAdapter(logging.getLogger("my_module"), request_id="req-1")
        logger.info("Processing started", extra={"span_id": "span-1"})
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        request_id: str = "",
        trace_id: str = "",
        span_id: str = "",
        error_code: str = "",
    ):
        self._logger = logger
        self._request_id = request_id
        self._trace_id = trace_id
        self._span_id = span_id
        self._error_code = error_code

    def _inject_extra(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        extra = kwargs.get("extra", {})
        if isinstance(extra, dict):
            if self._request_id:
                extra["request_id"] = self._request_id
            if self._trace_id:
                extra["trace_id"] = self._trace_id
            if self._span_id:
                extra["span_id"] = self._span_id
            if self._error_code:
                extra["error_code"] = self._error_code
            kwargs["extra"] = extra
        elif not extra:
            kwargs["extra"] = {
                k: v
                for k, v in [
                    ("request_id", self._request_id),
                    ("trace_id", self._trace_id),
                    ("span_id", self._span_id),
                    ("error_code", self._error_code),
                ]
                if v
            }
        return kwargs

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs = self._inject_extra(kwargs)
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs = self._inject_extra(kwargs)
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs = self._inject_extra(kwargs)
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs = self._inject_extra(kwargs)
        self._logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs = self._inject_extra(kwargs)
        self._logger.exception(msg, *args, **kwargs)

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def with_context(
        self,
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        error_code: str | None = None,
    ) -> StructuredLogAdapter:
        return StructuredLogAdapter(
            self._logger,
            request_id=request_id or self._request_id,
            trace_id=trace_id or self._trace_id,
            span_id=span_id or self._span_id,
            error_code=error_code or self._error_code,
        )
