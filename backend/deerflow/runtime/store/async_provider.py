'''按应用持久化配置创建异步 PostgreSQL 存储器，并管理连接生命周期。'''

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.store.base import BaseStore

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.persistence.langgraph_schema import ensure_langgraph_schema_async

logger = logging.getLogger(__name__)

POSTGRES_STORE_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL store. Install the package extra with: pip install 'deer-flow[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)


@contextlib.asynccontextmanager
async def make_store(app_config: AppConfig | None = None) -> AsyncIterator[BaseStore]:
    '''从传入或当前应用配置解析后端，创建异步存储器并在退出时释放连接。'''
    if app_config is None:
        app_config = get_app_config()

    connection_string = app_config.database.postgres_url
    if not connection_string:
        raise ValueError("database.postgres_url is required for the postgres backend")

    try:
        from langgraph.store.postgres.aio import AsyncPostgresStore
    except ImportError as exc:
        raise ImportError(POSTGRES_STORE_INSTALL) from exc

    async with AsyncPostgresStore.from_conn_string(connection_string) as store:
        await ensure_langgraph_schema_async(connection_string, 'store')
        logger.info("Store: using AsyncPostgresStore")
        yield store
