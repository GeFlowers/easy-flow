'定义 async_provider 模块提供的职责与可复用接口。\n\nAsync Store factory — backend mirrors runtime persistence configuration.\n\nThe deprecated ``checkpointer`` section takes precedence when present;\notherwise Store follows the unified ``database`` section in *config.yaml*:\n\n- ``memory``   → :class:`langgraph.store.memory.InMemoryStore`\n- ``sqlite``   → :class:`langgraph.store.sqlite.aio.AsyncSqliteStore`\n- ``postgres`` → :class:`langgraph.store.postgres.aio.AsyncPostgresStore`\n\nUsage (e.g. FastAPI lifespan)::\n\n    from deerflow.runtime.store import make_store\n\n    async with make_store() as store:\n        app.state.store = store\n'

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.store.base import BaseStore

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.runtime.store.provider import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_STORE_INSTALL,
    SQLITE_STORE_INSTALL,
    _resolve_store_config,
    ensure_sqlite_parent_dir,
    resolve_sqlite_conn_str,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal backend factory
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_store(config) -> AsyncIterator[BaseStore]:
    '执行 _async_store 的明确职责，并返回与调用约定一致的结果。\n\nAsync context manager that constructs and tears down a Store.\n\n    The ``config`` argument is a :class:`deerflow.config.checkpointer_config.CheckpointerConfig`\n    instance — the same object used by the checkpointer factory.\n    '
    if config.type == "memory":
        from langgraph.store.memory import InMemoryStore

        logger.info("Store: using InMemoryStore (in-process, not persistent)")
        yield InMemoryStore()
        return

    if config.type == "sqlite":
        try:
            from langgraph.store.sqlite.aio import AsyncSqliteStore
        except ImportError as exc:
            raise ImportError(SQLITE_STORE_INSTALL) from exc

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
        await asyncio.to_thread(ensure_sqlite_parent_dir, conn_str)

        async with AsyncSqliteStore.from_conn_string(conn_str) as store:
            await store.setup()
            logger.info("Store: using AsyncSqliteStore (%s)", conn_str)
            yield store
        return

    if config.type == "postgres":
        try:
            from langgraph.store.postgres.aio import AsyncPostgresStore  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(POSTGRES_STORE_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        async with AsyncPostgresStore.from_conn_string(config.connection_string) as store:
            await store.setup()
            logger.info("Store: using AsyncPostgresStore")
            yield store
        return

    raise ValueError(f"Unknown store backend type: {config.type!r}")


# ---------------------------------------------------------------------------
# Public async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def make_store(app_config: AppConfig | None = None) -> AsyncIterator[BaseStore]:
    '构造并返回，并遵守 make_store 所表达的接口约束。\n\nYield a Store selected from legacy or unified persistence config.\n\n    The legacy ``checkpointer`` section takes precedence when configured;\n    otherwise the unified ``database`` section selects the backend, matching\n    :func:`deerflow.runtime.checkpointer.async_provider.make_checkpointer`::\n\n        async with make_store(app_config) as store:\n            app.state.store = store\n\n    An :class:`~langgraph.store.memory.InMemoryStore` is returned only when the\n    resolved backend is explicitly ``memory``.\n    '
    if app_config is None:
        app_config = get_app_config()

    config = _resolve_store_config(app_config)
    async with _async_store(config) as store:
        yield store
