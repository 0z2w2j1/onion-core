from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

_logger = logging.getLogger(__name__)

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_span_id_var: ContextVar[str] = ContextVar("span_id", default="")
_error_code_var: ContextVar[str] = ContextVar("error_code", default="")


class RequestContext:
    def __init__(
        self,
        request_id: str = "",
        trace_id: str = "",
        span_id: str = "",
        error_code: str = "",
    ):
        self.request_id = request_id or uuid.uuid4().hex
        self.trace_id = trace_id or uuid.uuid4().hex
        self.span_id = span_id or ""
        self.error_code = error_code
        self._token: Any = None

    def __enter__(self) -> RequestContext:
        self._token = (
            _request_id_var.set(self.request_id),
            _trace_id_var.set(self.trace_id),
            _span_id_var.set(self.span_id),
            _error_code_var.set(self.error_code),
        )
        return self

    def __exit__(self, *args: Any) -> None:
        if self._token:
            _request_id_var.reset(self._token[0])
            _trace_id_var.reset(self._token[1])
            _span_id_var.reset(self._token[2])
            _error_code_var.reset(self._token[3])
            self._token = None

    def set_span(self, span_id: str) -> None:
        self.span_id = span_id
        old = _span_id_var.set(span_id)
        if self._token:
            self._token = (self._token[0], self._token[1], old, self._token[3])

    def set_error(self, error_code: str) -> None:
        self.error_code = error_code
        old = _error_code_var.set(error_code)
        if self._token:
            self._token = (self._token[0], self._token[1], self._token[2], old)


def set_context(
    request_id: str = "",
    trace_id: str = "",
    span_id: str = "",
    error_code: str = "",
) -> RequestContext:
    return RequestContext(
        request_id=request_id,
        trace_id=trace_id,
        span_id=span_id,
        error_code=error_code,
    )


def reset_context() -> None:
    _request_id_var.set("")
    _trace_id_var.set("")
    _span_id_var.set("")
    _error_code_var.set("")


def current_request_id() -> str:
    return _request_id_var.get()


def current_trace_id() -> str:
    return _trace_id_var.get()


def with_request_context(
    request_id: str = "",
    trace_id: str = "",
    span_id: str = "",
    error_code: str = "",
) -> RequestContext:
    return RequestContext(
        request_id=request_id,
        trace_id=trace_id,
        span_id=span_id,
        error_code=error_code,
    )


class StructuredLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id_var.get()
        trace_id = _trace_id_var.get()
        span_id = _span_id_var.get()
        error_code = _error_code_var.get()
        if request_id:
            record.request_id = request_id
        if trace_id:
            record.trace_id = trace_id
        if span_id:
            record.span_id = span_id
        if error_code:
            record.error_code = error_code
        return True
