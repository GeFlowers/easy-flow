"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

from functools import cache

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase


@cache
def _column_keys(cls: type) -> tuple[str, ...]:
    """缓存并返回 ORM 模型映射的列属性名称。"""
    return tuple(c.key for c in sa_inspect(cls).mapper.column_attrs)


class Base(DeclarativeBase):
    """定义持久化层使用的数据模型、配置或辅助组件。"""

    def to_dict(self, *, exclude: set[str] | None = None) -> dict:
        """将持久化记录转换为对外使用的字典表示。"""
        keys = _column_keys(type(self))
        if exclude:
            return {k: getattr(self, k) for k in keys if k not in exclude}
        return {k: getattr(self, k) for k in keys}

    def __repr__(self) -> str:
        """返回便于调试的对象文本表示。"""
        cols = ", ".join(f"{k}={getattr(self, k)!r}" for k in _column_keys(type(self)))
        return f"{type(self).__name__}({cols})"
