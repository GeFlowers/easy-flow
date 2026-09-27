"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def _json_serializer(obj: object) -> str:
    """处理持久化层使用的结构化数据校验、绑定或比较。"""
    return json.dumps(obj, ensure_ascii=False)


logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def _auto_create_postgres_db(url: str) -> None:
    """执行持久化流程所需的内部辅助操作。"""
    from sqlalchemy import text
    from sqlalchemy.engine.url import make_url

    parsed = make_url(url)
    db_name = parsed.database
    if not db_name:
        raise ValueError("Cannot auto-create database: no database name in URL")

        # 中文说明：此处用于执行相关处理。
    maint_url = parsed.set(database="postgres")
    maint_engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    try:
        async with maint_engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        logger.info("Auto-created PostgreSQL database: %s", db_name)
    finally:
        await maint_engine.dispose()


async def init_engine(
    backend: str,
    *,
    url: str = "",
    echo: bool = False,
    pool_size: int = 5,
    sqlite_dir: str = "",
) -> None:
    """执行当前持久化组件提供的操作。"""
    global _engine, _session_factory

    if backend == "postgres":
        try:
            import asyncpg  # noqa: F401
        except ImportError:
            raise ImportError(
                "database.backend is set to 'postgres' but asyncpg is not installed.\n"
                "Install it with:\n"
                "    cd backend && uv sync --all-packages --extra postgres\n"
                "On the next `make dev` the postgres extra is auto-detected from\n"
                "config.yaml (database.backend: postgres) and reinstalled, so it\n"
                "will not be wiped again. Set UV_EXTRAS=postgres in .env to opt in\n"
                "explicitly. Or switch to backend: sqlite in config.yaml for\n"
                "single-node deployment."
            ) from None

    if backend == "sqlite":
        import os

        from sqlalchemy import event

        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        await asyncio.to_thread(os.makedirs, sqlite_dir or ".", exist_ok=True)
        _engine = create_async_engine(url, echo=echo, json_serializer=_json_serializer)

        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        @event.listens_for(_engine.sync_engine, "connect")
        def _enable_sqlite_wal(dbapi_conn, _record):  # noqa: ARG001 — SQLAlchemy contract
            """执行持久化流程所需的内部辅助操作。"""
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.execute("PRAGMA busy_timeout=30000;")
            finally:
                cursor.close()
    elif backend == "postgres":
        _engine = create_async_engine(
            url,
            echo=echo,
            pool_size=pool_size,
            pool_pre_ping=True,
            json_serializer=_json_serializer,
        )
    else:
        raise ValueError(f"Unknown persistence backend: {backend!r}")

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    # 中文说明：此处用于执行相关处理。
    from deerflow.persistence.bootstrap import bootstrap_schema

    try:
        await bootstrap_schema(_engine, backend=backend)
    except Exception as exc:
        if backend == "postgres" and "does not exist" in str(exc):
            # 中文说明：此处用于执行相关处理。
            await _auto_create_postgres_db(url)
            # 中文说明：此处用于执行相关处理。
            await _engine.dispose()
            _engine = create_async_engine(url, echo=echo, pool_size=pool_size, pool_pre_ping=True, json_serializer=_json_serializer)
            _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
            await bootstrap_schema(_engine, backend=backend)
        else:
            raise

    logger.info("Persistence engine initialized: backend=%s", backend)


async def init_engine_from_config(config) -> None:
    """执行当前持久化组件提供的操作。"""
    await init_engine(
        backend=config.backend,
        url=config.app_sqlalchemy_url,
        echo=config.echo_sql,
        pool_size=config.pool_size,
        sqlite_dir=config.sqlite_dir if config.backend == "sqlite" else "",
    )


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """按给定条件查询并返回对应的持久化记录。"""
    return _session_factory


def get_engine() -> AsyncEngine | None:
    """按给定条件查询并返回对应的持久化记录。"""
    return _engine


async def close_engine() -> None:
    """执行当前持久化组件提供的操作。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Persistence engine closed")
    _engine = None
    _session_factory = None
