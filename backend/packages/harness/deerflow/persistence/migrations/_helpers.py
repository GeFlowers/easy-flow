"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)


def _inspector() -> sa.Inspector:
    """创建指向当前 Alembic 迁移连接的数据库结构检查器。"""
    return sa.inspect(op.get_bind())


def _normalize_default(value: object) -> str | None:
    """规范化数据库反射出的默认值表达式，便于与模型定义比较。"""
    if value is None:
        return None
    if isinstance(value, sa.sql.elements.TextClause):
        text = value.text
    elif isinstance(value, sa.schema.DefaultClause) and isinstance(value.arg, sa.sql.elements.TextClause):
        text = value.arg.text
    else:
        text = str(value)
    text = text.strip()
    # Strip a single layer of outer parens that some dialects wrap defaults in.
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    # Strip Postgres-style type casts like ``'{}'::jsonb``.
    if "::" in text:
        text = text.split("::", 1)[0].strip()
    return text or None


def _normalize_type(value: object) -> str:
    """去除类型参数并统一大小写，得到可比较的 SQL 类型名。"""
    if value is None:
        return ""
    s = value if isinstance(value, str) else repr(value)
    return s.upper().split("(", 1)[0].strip()


# Known dialect-synonym pairs that must NOT fire a type-drift warning.
# Postgres reflects ``JSON`` as ``JSONB`` (and vice versa depending on how
# the column was provisioned); the model's ``sa.JSON`` plus this allowlist
# keeps a Postgres deployment quiet while still catching genuine type errors
# like ``TEXT NOT NULL DEFAULT '{}'`` re-adds.
#
# Add a new pair here ONLY when a real reflection-vs-model mismatch is
# proven to be a false positive in a deployment -- not pre-emptively, since
# overly broad equivalence would re-open the silent-drift hole this helper
# exists to close.
_EQUIVALENT_TYPE_FAMILIES: tuple[frozenset[str], ...] = (frozenset({"JSON", "JSONB"}),)


def _type_equivalent(actual: object, desired: object) -> bool:
    """判断数据库类型与模型类型是否相同或属于已确认的方言等价类型。"""
    a = _normalize_type(actual)
    d = _normalize_type(desired)
    if not a or not d:
        return True
    if a == d:
        return True
    pair = frozenset({a, d})
    return any(pair <= fam for fam in _EQUIVALENT_TYPE_FAMILIES)


def _check_column_drift(table: str, desired: sa.Column, actual: dict) -> None:
    """检查已有列与模型定义的类型、可空性及默认值差异并记录警告。"""
    diffs: list[str] = []

    desired_nullable = True if desired.nullable is None else bool(desired.nullable)
    actual_nullable = bool(actual.get("nullable", True))
    if desired_nullable != actual_nullable:
        diffs.append(f"nullable actual={actual_nullable} desired={desired_nullable}")

    desired_default = _normalize_default(desired.server_default)
    actual_default = _normalize_default(actual.get("default"))
    if desired_default != actual_default:
        diffs.append(f"server_default actual={actual_default!r} desired={desired_default!r}")

    if not _type_equivalent(actual.get("type"), desired.type):
        diffs.append(f"type actual={_normalize_type(actual.get('type'))!r} desired={_normalize_type(desired.type)!r}")

    if diffs:
        logger.warning(
            "safe_add_column: %s.%s already exists but drifts from the model definition (%s); actual_type=%r desired_type=%r; leaving as-is -- a manual ALTER may be needed to match the model.",
            table,
            desired.name,
            "; ".join(diffs),
            actual.get("type"),
            desired.type,
        )


def safe_add_column(table: str, column: sa.Column) -> None:
    """仅在目标列缺失时添加列；已存在但定义不一致时保留现状并告警。"""
    insp = _inspector()
    if table not in insp.get_table_names():
        return
    existing = {c["name"]: c for c in insp.get_columns(table)}
    if column.name in existing:
        _check_column_drift(table, column, existing[column.name])
        return
    with op.batch_alter_table(table) as batch:
        batch.add_column(column)


def safe_drop_column(table: str, column_name: str) -> None:
    """仅当表和列均存在时删除列，使迁移可兼容部分升级过的数据库。"""
    insp = _inspector()
    if table not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    if column_name not in existing:
        return
    with op.batch_alter_table(table) as batch:
        batch.drop_column(column_name)
