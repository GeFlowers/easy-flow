'''

Async checkpointer factory.

Provides an **async context manager** for long-running async servers that need
proper resource cleanup.

Supported database backend: PostgreSQL. The legacy standalone
``checkpointer`` configuration may still provide the PostgreSQL DSN.

Usage (e.g. FastAPI lifespan)::

    from deerflow.runtime.checkpointer.async_provider import make_checkpointer

    async with make_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer

For sync usage see :mod:`deerflow.runtime.checkpointer.provider`.
'''

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.runtime.checkpointer.provider import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_INSTALL,
)

logger = logging.getLogger(__name__)


def _build_postgres_pool(conn_string: str):
    '''

    构建：an AsyncConnectionPool with TCP keepalive and connection checking.'''
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    return AsyncConnectionPool(
        conn_string,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "keepalives": 1,
            "keepalives_idle": 60,
            "keepalives_interval": 10,
            "keepalives_count": 6,
        },
        check=AsyncConnectionPool.check_connection,
    )


def _ensure_postgres_imports():
    '''

    加载 PostgreSQL 检查点依赖，缺少可选包时给出安装指引。'''
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        raise ImportError(POSTGRES_INSTALL) from exc

    try:
        from psycopg_pool import AsyncConnectionPool
    except ImportError as exc:
        raise ImportError(POSTGRES_INSTALL) from exc

    return AsyncPostgresSaver, AsyncConnectionPool




@contextlib.asynccontextmanager
async def _async_checkpointer(config) -> AsyncIterator[Checkpointer]:
    '''

    异步上下文管理器： that constructs and tears down a checkpointer.'''
    if config.type == "postgres":
        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        AsyncPostgresSaver, _ = _ensure_postgres_imports()
        pool = _build_postgres_pool(config.connection_string)
        async with pool:
            saver = AsyncPostgresSaver(conn=pool)
            await saver.setup()
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")




@contextlib.asynccontextmanager
async def _async_checkpointer_from_database(db_config) -> AsyncIterator[Checkpointer]:
    '''

    异步上下文管理器： that constructs a checkpointer from unified DatabaseConfig.'''
    if db_config.backend == "postgres":
        if not db_config.postgres_url:
            raise ValueError("database.postgres_url is required for the postgres backend")

        AsyncPostgresSaver, _ = _ensure_postgres_imports()
        pool = _build_postgres_pool(db_config.postgres_url)
        async with pool:
            saver = AsyncPostgresSaver(conn=pool)
            await saver.setup()
            yield saver
        return

    raise ValueError(f"Unknown database backend: {db_config.backend!r}")


@contextlib.asynccontextmanager
async def make_checkpointer(app_config: AppConfig | None = None) -> AsyncIterator[Checkpointer]:
    '''

    异步上下文管理器： that yields a checkpointer for the caller's lifetime.
        Resources are opened on enter and closed on exit -- no global state::

            async with make_checkpointer(app_config) as checkpointer:
                app.state.checkpointer = checkpointer

        Priority:
        1. Legacy ``checkpointer:`` config section (backward compatible)
        2. Unified ``database:`` config section
    '''

    if app_config is None:
        app_config = get_app_config()

    if app_config.checkpointer is not None:
        async with _async_checkpointer(app_config.checkpointer) as saver:
            yield saver
            return

    db_config = getattr(app_config, "database", None)
    if db_config is not None:
        async with _async_checkpointer_from_database(db_config) as saver:
            yield saver
            return

    raise RuntimeError("PostgreSQL checkpointer configuration is required")
