"""管理鹿流请求级追踪上下文。

此处保存的关联标识独立于第三方追踪标识和鹿流运行标识，用于响应
响应头、日志及可选追踪元数据之间的关联。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Final

TRACE_ID_HEADER: Final[str] = "X-Trace-Id"
DEERFLOW_TRACE_METADATA_KEY: Final[str] = "deerflow_trace_id"
_MAX_TRACE_ID_LENGTH: Final[int] = 512

_current_trace_id: Final[ContextVar[str | None]] = ContextVar("deerflow_current_trace_id", default=None)


def generate_trace_id() -> str:
    """生成新的、可安全写入响应头的十六进制追踪标识。"""
    return uuid.uuid4().hex


def normalize_trace_id(value: object) -> str | None:
    """校验并规范化追踪标识；不可用值返回空值。

    仅接受长度受限的可打印基础拉丁字符，拒绝控制字符和其他字符，避免响应头编码
    失败、代理剥离字段或日志注入。
    """
    if not isinstance(value, str):
        return None
    trace_id = value.strip()
    if not trace_id or len(trace_id) > _MAX_TRACE_ID_LENGTH:
        return None
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in trace_id):
        return None
    return trace_id


def set_current_trace_id(trace_id: str) -> Token[str | None]:
    """将合法追踪标识绑定至当前执行上下文，并返回可复位令牌。"""
    normalized = normalize_trace_id(trace_id)
    if normalized is None:
        normalized = generate_trace_id()
    return _current_trace_id.set(normalized)


def reset_current_trace_id(token: Token[str | None]) -> None:
    """使用令牌恢复绑定前的追踪上下文。"""
    _current_trace_id.reset(token)


def get_current_trace_id() -> str | None:
    """返回当前上下文已绑定的请求追踪标识；未绑定时返回空值。"""
    return _current_trace_id.get()


@contextmanager
def request_trace_context(trace_id: str | None = None) -> Iterator[str]:
    """在上下文管理器范围内绑定指定或新生成的请求追踪标识。"""
    normalized = normalize_trace_id(trace_id) or generate_trace_id()
    token = _current_trace_id.set(normalized)
    try:
        yield normalized
    finally:
        _current_trace_id.reset(token)


@contextmanager
def ensure_trace_context(trace_id: str | None = None) -> Iterator[str]:
    """优先绑定给定标识，否则继承当前标识，均无时创建新的标识。"""
    normalized = normalize_trace_id(trace_id) or get_current_trace_id() or generate_trace_id()
    token = _current_trace_id.set(normalized)
    try:
        yield normalized
    finally:
        _current_trace_id.reset(token)
