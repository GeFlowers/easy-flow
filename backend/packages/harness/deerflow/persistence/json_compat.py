'''为 PostgreSQL JSONB 元数据字段构造经过校验的类型匹配条件。'''

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import BigInteger, Float, String, bindparam
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.expression import ColumnElement
from sqlalchemy.sql.visitors import InternalTraversal
from sqlalchemy.types import Boolean, TypeEngine

_KEY_CHARSET_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
ALLOWED_FILTER_VALUE_TYPES: tuple[type, ...] = (type(None), bool, int, float, str)


def validate_metadata_filter_key(key: object) -> bool:
    '''检查 JSON 字段名是否只包含 SQL 路径允许的字符。'''
    return isinstance(key, str) and bool(_KEY_CHARSET_RE.fullmatch(key))


def validate_metadata_filter_value(value: object) -> bool:
    '''限制元数据筛选值为 JSON 标量，并确保整数能由 PostgreSQL BIGINT 表示。'''
    if not isinstance(value, ALLOWED_FILTER_VALUE_TYPES):
        return False
    return not isinstance(value, int) or isinstance(value, bool) or _INT64_MIN <= value <= _INT64_MAX


class JsonMatch(ColumnElement[bool]):
    '''表示一个 PostgreSQL JSONB 对象字段的类型安全相等条件。'''

    inherit_cache = True
    type = Boolean()
    _is_implicitly_boolean = True
    _traverse_internals = [
        ("column", InternalTraversal.dp_clauseelement),
        ("key", InternalTraversal.dp_string),
        ("value", InternalTraversal.dp_plain_obj),
    ]

    def __init__(self, column: ColumnElement[Any], key: str, value: object) -> None:
        '''验证筛选条件并保存 SQLAlchemy 编译器需要的列、键和值。'''
        if not validate_metadata_filter_key(key):
            raise ValueError(f"JsonMatch key must match {_KEY_CHARSET_RE.pattern!r}; got: {key!r}")
        if not validate_metadata_filter_value(value):
            if isinstance(value, int) and not isinstance(value, bool):
                raise TypeError(f"JsonMatch integer is outside signed 64-bit range: {value!r}")
            raise TypeError(f"JsonMatch value must be a JSON scalar; got: {type(value).__name__!r}")
        self.column = column
        self.key = key
        self.value = value
        super().__init__()


def _bind(compiler: SQLCompiler, value: object, value_type: TypeEngine[Any], **kw: Any) -> str:
    '''把筛选值作为有明确 SQL 类型的绑定参数交给驱动。'''
    return compiler.process(bindparam(None, value, type_=value_type), **kw)


def _compile_postgres(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    '''生成 PostgreSQL JSONB 标量比较，避免跨类型隐式转换造成误匹配。'''
    if not validate_metadata_filter_key(element.key):
        raise ValueError(f"Key escaped validation: {element.key!r}")

    column = compiler.process(element.column, **kw)
    value_type = f"json_typeof({column} -> '{element.key}')"
    extracted_value = f"({column} ->> '{element.key}')"
    value = element.value

    if value is None:
        return f"{value_type} = 'null'"
    if isinstance(value, bool):
        expected = "true" if value else "false"
        return f"({value_type} = 'boolean' AND {extracted_value} = '{expected}')"
    if isinstance(value, int):
        parameter = _bind(compiler, value, BigInteger(), **kw)
        return f"({value_type} = 'number' AND {extracted_value} ~ '^-?[0-9]+$' AND CAST({extracted_value} AS BIGINT) = {parameter})"
    if isinstance(value, float):
        parameter = _bind(compiler, value, Float(), **kw)
        return f"({value_type} = 'number' AND CAST({extracted_value} AS DOUBLE PRECISION) = {parameter})"

    parameter = _bind(compiler, value, String(), **kw)
    return f"({value_type} = 'string' AND {extracted_value} = {parameter})"


@compiles(JsonMatch, "postgresql")
def _compile_postgres_json_match(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    '''将 JSON 匹配表达式委托给 PostgreSQL SQL 生成器。'''
    return _compile_postgres(element, compiler, **kw)


@compiles(JsonMatch)
def _reject_unsupported_json_match(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    '''对未配置的数据库方言明确报错，避免生成不兼容的 JSON 查询。'''
    raise NotImplementedError(f"JsonMatch supports only PostgreSQL; got dialect: {compiler.dialect.name}")


def json_match(column: ColumnElement[Any], key: str, value: object) -> JsonMatch:
    '''创建 JSONB 键值条件，供线程元数据搜索组合到 SQLAlchemy 查询中。'''
    return JsonMatch(column, key, value)
