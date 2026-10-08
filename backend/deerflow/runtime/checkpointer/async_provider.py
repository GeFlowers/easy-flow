'''

异步检查点保存器工厂。

为需要正确清理资源的常驻异步服务提供**异步上下文管理器**。

支持 PostgreSQL 后端；旧版独立 ``checkpointer`` 配置仍可提供连接字符串。

用法（例如 FastAPI 生命周期管理）::

    from deerflow.runtime.checkpointer.async_provider import make_checkpointer

    async with make_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer

同步用法见 :mod:`deerflow.runtime.checkpointer.provider`。
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

    构建启用连接保活和连接检查的 AsyncConnectionPool。'''
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

    创建检查点保存器，并在异步上下文退出时释放资源。'''
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

    根据统一 DatabaseConfig 创建检查点保存器，并管理异步资源生命周期。'''
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

    提供在调用方上下文存续期间可用的检查点保存器。
        进入时打开资源，退出时关闭资源，不使用全局状态::

            async with make_checkpointer(app_config) as checkpointer:
                app.state.checkpointer = checkpointer

        配置优先级：
        1. 旧版 ``checkpointer:`` 配置节（向后兼容）。
        2. 统一 ``database:`` 配置节。
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
