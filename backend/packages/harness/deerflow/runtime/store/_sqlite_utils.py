"""定义 _sqlite_utils 模块提供的职责与可复用接口。

Shared SQLite connection utilities for store and checkpointer providers."""

from __future__ import annotations

import pathlib

from deerflow.config.paths import resolve_path


def resolve_sqlite_conn_str(raw: str) -> str:
    """执行 resolve_sqlite_conn_str 的明确职责，并返回与调用约定一致的结果。

    Return a SQLite connection string ready for use with store/checkpointer backends.

        SQLite special strings (``":memory:"`` and ``file:`` URIs) are returned
        unchanged.  Plain filesystem paths — relative or absolute — are resolved
        to an absolute string via :func:`resolve_path`.
    """
    if raw == ":memory:" or raw.startswith("file:"):
        return raw
    return str(resolve_path(raw))


def ensure_sqlite_parent_dir(conn_str: str) -> None:
    """执行 ensure_sqlite_parent_dir 的明确职责，并返回与调用约定一致的结果。

    Create parent directory for a SQLite filesystem path.

        No-op for in-memory databases (``":memory:"``) and ``file:`` URIs.
    """
    if conn_str != ":memory:" and not conn_str.startswith("file:"):
        pathlib.Path(conn_str).parent.mkdir(parents=True, exist_ok=True)
