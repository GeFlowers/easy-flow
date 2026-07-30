"""处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

__all__ = ["coerce_iso", "is_lease_expired", "now_iso"]


def is_lease_expired(lease_expires_at: str | None, *, grace_seconds: int) -> bool:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
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
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    return datetime.now(UTC).isoformat()


def coerce_iso(value: object) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
                # ????????????????
        return str(value)
    if isinstance(value, datetime):
                # ????????????????
                # ????????????????
                # ????????????????
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
