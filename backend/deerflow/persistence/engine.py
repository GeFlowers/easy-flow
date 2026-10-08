'''管理 PostgreSQL 引擎、数据库结构初始化及异步会话生命周期。'''

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _json_serializer(value: object) -> str:
    '''序列化 JSON 字段并保留其中的 Unicode 字符。'''
    return json.dumps(value, ensure_ascii=False)


async def _auto_create_postgres_db(url: str) -> None:
    '''目标数据库不存在时，连接维护库并创建目标数据库。'''
    from sqlalchemy import text
    from sqlalchemy.engine.url import make_url

    parsed_url = make_url(url)
    database_name = parsed_url.database
    if not database_name:
        raise ValueError("Cannot auto-create database: no database name in URL")

    maintenance_url = parsed_url.set(database="postgres")
    maintenance_engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        async with maintenance_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        logger.info("Auto-created PostgreSQL database: %s", database_name)
    finally:
        await maintenance_engine.dispose()


def _create_engine(url: str, *, echo: bool, pool_size: int) -> AsyncEngine:
    '''创建供网关各个仓储共用的异步连接池。'''
    return create_async_engine(
        url,
        echo=echo,
        pool_size=pool_size,
        pool_pre_ping=True,
        json_serializer=_json_serializer,
    )


async def init_engine(
    backend: str,
    *,
    url: str = "",
    echo: bool = False,
    pool_size: int = 5,
) -> None:
    '''建立 PostgreSQL 连接池并将数据库架构升级到当前版本。'''
    global _engine, _session_factory

    if backend != "postgres":
        raise ValueError(f"Unknown persistence backend: {backend!r}; only 'postgres' is supported")
    if not url:
        raise ValueError("database.postgres_url is required for the postgres backend")

    try:
        import asyncpg  # noqa: F401
    except ImportError:
        raise ImportError(
            "PostgreSQL persistence requires asyncpg. Install it with: "
            "cd backend && uv sync --all-packages --extra postgres"
        ) from None

    _engine = _create_engine(url, echo=echo, pool_size=pool_size)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    from deerflow.persistence.bootstrap import bootstrap_schema

    try:
        await bootstrap_schema(_engine)
    except Exception as exc:
        if "does not exist" not in str(exc):
            raise
        await _auto_create_postgres_db(url)
        await _engine.dispose()
        _engine = _create_engine(url, echo=echo, pool_size=pool_size)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        await bootstrap_schema(_engine)

    logger.info("Persistence engine initialized: backend=postgres")


async def init_engine_from_config(config) -> None:
    '''读取 DatabaseConfig 并初始化共享数据库引擎。'''
    await init_engine(
        backend=config.backend,
        url=config.app_sqlalchemy_url,
        echo=config.echo_sql,
        pool_size=config.pool_size,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    '''返回共享异步会话工厂；引擎尚未初始化时返回 ``None``。'''
    return _session_factory


def get_engine() -> AsyncEngine | None:
    '''返回当前 SQLAlchemy 引擎；引擎尚未初始化时返回 ``None``。'''
    return _engine


async def close_engine() -> None:
    '''释放连接池，并清空共享引擎和会话工厂引用。'''
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Persistence engine closed")
    _engine = None
    _session_factory = None
