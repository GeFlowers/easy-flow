'''统一处理运行租约时间、当前 UTC 时间和兼容旧格式的时间戳。'''

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

__all__ = ["coerce_iso", "is_lease_expired", "now_iso"]


def is_lease_expired(lease_expires_at: str | None, *, grace_seconds: int) -> bool:
    '''解析租约截止时间，并在缺失、格式错误或宽限期已过时判定为过期。'''
    if lease_expires_at is None:
        return True
    try:
        dt = datetime.fromisoformat(lease_expires_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return True
    return dt < datetime.now(UTC) - timedelta(seconds=grace_seconds)


_UNIX_TIMESTAMP_PATTERN = re.compile(r"^\d{10}(?:\.\d+)?$")
"""Matches the unix-timestamp string shape historically written by
``str(time.time())`` (10-digit seconds with optional fractional part).
The 10-digit anchor avoids accidentally rewriting ISO years like
``"2026"`` and stays valid until the year 2286.
"""


def now_iso() -> str:
    '''返回带时区信息的当前 UTC ISO 时间字符串。'''
    return datetime.now(UTC).isoformat()


def coerce_iso(value: object) -> str:
    '''把日期对象、数值时间戳和旧式时间字符串规范化为 ISO 字符串。'''
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        # 布尔值是整数子类，但不能将 True/False 当作 Unix 时间戳解释。
        return str(value)
    if isinstance(value, datetime):
        # 无时区时间按 UTC 解释；有时区时间先转换到 UTC 再序列化。
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            return str(value)
    if isinstance(value, str):
        if _UNIX_TIMESTAMP_PATTERN.match(value):
            try:
                return datetime.fromtimestamp(float(value), UTC).isoformat()
            except (ValueError, OverflowError, OSError):
                return value
        return value
    return str(value)
