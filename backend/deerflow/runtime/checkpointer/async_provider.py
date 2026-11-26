'''按应用持久化配置创建异步 PostgreSQL 检查点保存器。'''

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.persistence.langgraph_schema import ensure_langgraph_schema_async


POSTGRES_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install the package extra with: pip install 'deer-flow[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)


@contextlib.asynccontextmanager
async def make_checkpointer(app_config: AppConfig | None = None) -> AsyncIterator[Checkpointer]:
    '''从应用数据库配置创建检查点保存器，并在退出时关闭连接池。'''
    if app_config is None:
        app_config = get_app_config()
    connection_string = app_config.database.postgres_url
    if not connection_string:
        raise ValueError("database.postgres_url is required for the postgres backend")

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
    except ImportError as exc:
        raise ImportError(POSTGRES_INSTALL) from exc

    pool = AsyncConnectionPool(
        connection_string,
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
    async with pool:
        saver = AsyncPostgresSaver(conn=pool)
        await ensure_langgraph_schema_async(connection_string, 'checkpoint')
        yield saver
