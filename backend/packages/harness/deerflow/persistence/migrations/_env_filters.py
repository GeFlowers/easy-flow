"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

# Tables owned by LangGraph -- alembic must never propose DDL for them.
LANGGRAPH_OWNED_TABLES: frozenset[str] = frozenset(
    {
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    }
)


def include_object(object_, name, type_, reflected, compare_to):  # noqa: ARG001
    """执行当前持久化组件提供的操作。"""
    if type_ == "table" and name in LANGGRAPH_OWNED_TABLES:
        return False
    parent_table = getattr(object_, "table", None)
    if parent_table is not None and getattr(parent_table, "name", None) in LANGGRAPH_OWNED_TABLES:
        return False
    return True
