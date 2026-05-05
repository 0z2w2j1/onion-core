"""Pipeline 输入验证：防止恶意构造的 DoS payload（超大消息、Unicode 炸弹、过深嵌套）。

独立模块便于单测与复用。所有常量和函数与 Pipeline 内嵌实现的语义完全一致。
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from .error_codes import ErrorCode
from .models import _MAX_TOOL_CALL_DEPTH, AgentContext, ValidationError

MAX_MESSAGES = 1000
MAX_CONTENT_LENGTH = 1_000_000
MAX_CONTENT_BLOCKS = 50
MAX_METADATA_BYTES = 1_000_000
MAX_METADATA_KEYS = 100
MAX_CONFIG_DEPTH = 3

_UNICODE_COMBINING_THRESHOLD = 0.3
_UNICODE_BOMB_MIN_CHARS = 10


def detect_unicode_bomb(text: str) -> bool:
    """检测 Zalgo 式 Unicode 炸弹（组合字符占比超阈值）。"""
    if not text:
        return False
    total_chars = len(text)
    if total_chars < _UNICODE_BOMB_MIN_CHARS:
        return False
    threshold_count = max(2, int(total_chars * _UNICODE_COMBINING_THRESHOLD) + 1)
    combining_count = 0
    for c in text:
        if unicodedata.combining(c):
            combining_count += 1
            if combining_count >= threshold_count:
                return True
    return False


def config_depth(obj: Any, depth: int = 0) -> int:
    """返回字典嵌套深度，深度达到 MAX_CONFIG_DEPTH 时提前退出。"""
    if not isinstance(obj, dict) or depth >= MAX_CONFIG_DEPTH:
        return depth
    return max((config_depth(v, depth + 1) for v in obj.values()), default=depth)


def validate_context(context: AgentContext) -> None:
    """校验 AgentContext 防止 DoS。失败时抛 ValidationError。"""
    if len(context.messages) > MAX_MESSAGES:
        raise ValidationError(
            f"Too many messages: {len(context.messages)} (max: {MAX_MESSAGES})",
            error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
        )

    for i, msg in enumerate(context.messages):
        if isinstance(msg.content, str):
            if len(msg.content) > MAX_CONTENT_LENGTH:
                raise ValidationError(
                    f"Message {i} content too long: {len(msg.content)} chars "
                    f"(max: {MAX_CONTENT_LENGTH})",
                    error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                )
            if detect_unicode_bomb(msg.content):
                raise ValidationError(
                    f"Message {i} contains suspicious Unicode characters (possible Zalgo text)",
                    error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                )
        elif isinstance(msg.content, list):
            total_length = sum(
                len(block.text) if block.text else 0
                for block in msg.content
                if block.type == "text"
            )
            if total_length > MAX_CONTENT_LENGTH:
                raise ValidationError(
                    f"Message {i} multimodal content too long: {total_length} chars "
                    f"(max: {MAX_CONTENT_LENGTH})",
                    error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                )
            if len(msg.content) > MAX_CONTENT_BLOCKS:
                raise ValidationError(
                    f"Message {i} has too many content blocks: {len(msg.content)} "
                    f"(max: {MAX_CONTENT_BLOCKS})",
                    error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                )
            for block_idx, block in enumerate(msg.content):
                if block.type == "text" and block.text and detect_unicode_bomb(block.text):
                    raise ValidationError(
                        f"Message {i} block {block_idx} contains suspicious Unicode characters",
                        error_code=ErrorCode.VALIDATION_INVALID_MESSAGE,
                    )

    if context.metadata.get("tool_calls_depth", 0) > _MAX_TOOL_CALL_DEPTH:
        raise ValidationError(
            f"Tool call nesting depth exceeded: {context.metadata['tool_calls_depth']} "
            f"(max: {_MAX_TOOL_CALL_DEPTH})",
            error_code=ErrorCode.VALIDATION_INVALID_TOOL_CALL,
        )

    try:
        metadata_size = len(json.dumps(context.metadata, default=str))
    except (TypeError, ValueError):
        metadata_size = len(str(context.metadata))
    if metadata_size > MAX_METADATA_BYTES:
        raise ValidationError(
            f"Metadata too large: {metadata_size} bytes (max: 1MB)",
            error_code=ErrorCode.VALIDATION_INVALID_CONTEXT,
        )

    if len(context.metadata) > MAX_METADATA_KEYS:
        raise ValidationError(
            f"Metadata has too many keys: {len(context.metadata)} (max: {MAX_METADATA_KEYS})",
            error_code=ErrorCode.VALIDATION_INVALID_CONTEXT,
        )

    if config_depth(context.config) > MAX_CONFIG_DEPTH:
        raise ValidationError(
            f"Config nesting depth exceeds limit (max: {MAX_CONFIG_DEPTH})",
            error_code=ErrorCode.VALIDATION_INVALID_CONFIG,
        )
