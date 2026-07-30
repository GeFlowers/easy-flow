'定义 provider 模块提供的职责与可复用接口。\n\nSync Store factory.\n\nProvides a **sync singleton** and a **sync context manager** for CLI tools\nand the embedded :class:`~deerflow.client.DeerFlowClient`.\n\nThe deprecated ``checkpointer`` section takes precedence when present;\notherwise Store follows the unified ``database`` section. Supported backends:\nmemory, sqlite, postgres.\n\nUsage::\n\n    from deerflow.runtime.store.provider import get_store, store_context\n\n    # Singleton — reused across calls, closed on process exit\n    store = get_store()\n\n    # One-shot — fresh connection, closed on block exit\n    with store_context() as store:\n        store.put(("ns",), "key", {"value": 1})\n'

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator

from langgraph.store.base import BaseStore

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig, ensure_config_loaded, get_checkpointer_config
from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir, resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error message constants
# ---------------------------------------------------------------------------

SQLITE_STORE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite store. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_STORE_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL store. Install the package extra with: pip install 'deerflow-harness[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"


def _resolve_store_config(app_config: AppConfig) -> CheckpointerConfig:
    '执行 _resolve_store_config 的明确职责，并返回与调用约定一致的结果。\n\nResolve the Store backend from legacy or unified application config.\n\n    The legacy ``checkpointer`` section remains authoritative when present so\n    Store and Checkpointer continue to use the same backend. Otherwise the\n    unified ``database`` section drives the Store as documented.\n    '
    if app_config.checkpointer is not None:
        return app_config.checkpointer

    database = app_config.database
    if database is None or database.backend == "memory":
        return CheckpointerConfig(type="memory")
    if database.backend == "sqlite":
        return CheckpointerConfig(type="sqlite", connection_string=database.checkpointer_sqlite_path)
    if database.backend == "postgres":
        if not database.postgres_url:
            raise ValueError("database.postgres_url is required for the postgres backend")
        return CheckpointerConfig(type="postgres", connection_string=database.postgres_url)
    raise ValueError(f"Unknown database backend: {database.backend!r}")


def _get_store_config() -> CheckpointerConfig:
    '执行 _get_store_config 的明确职责，并返回与调用约定一致的结果。\n\nLoad Store config without holding the provider singleton lock.'
    ensure_config_loaded()

    # Preserve callers that initialise the legacy config singleton directly.
    legacy_config = get_checkpointer_config()
    if legacy_config is not None:
        return legacy_config
    try:
        app_config = get_app_config()
    except FileNotFoundError:
        return CheckpointerConfig(type="memory")
    return _resolve_store_config(app_config)


# ---------------------------------------------------------------------------
# Sync factory
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _sync_store_cm(config) -> Iterator[BaseStore]:
    '执行 _sync_store_cm 的明确职责，并返回与调用约定一致的结果。\n\nContext manager that creates and tears down a sync Store.\n\n    The ``config`` argument is a\n    :class:`~deerflow.config.checkpointer_config.CheckpointerConfig` instance —\n    the same object used by the checkpointer factory.\n    '
    if config.type == "memory":
        from langgraph.store.memory import InMemoryStore

        logger.info("Store: using InMemoryStore (in-process, not persistent)")
        yield InMemoryStore()
        return

    if config.type == "sqlite":
        try:
            from langgraph.store.sqlite import SqliteStore
        except ImportError as exc:
            raise ImportError(SQLITE_STORE_INSTALL) from exc

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
        ensure_sqlite_parent_dir(conn_str)

        with SqliteStore.from_conn_string(conn_str) as store:
            store.setup()
            logger.info("Store: using SqliteStore (%s)", conn_str)
            yield store
        return

    if config.type == "postgres":
        try:
            from langgraph.store.postgres import PostgresStore  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(POSTGRES_STORE_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        with PostgresStore.from_conn_string(config.connection_string) as store:
            store.setup()
            logger.info("Store: using PostgresStore")
            yield store
        return

    raise ValueError(f"Unknown store backend type: {config.type!r}")


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_store: BaseStore | None = None
_store_ctx = None  # open context manager keeping the connection alive
_store_lock = threading.Lock()


def get_store() -> BaseStore:
    '读取并返回，并遵守 get_store 所表达的接口约束。\n\nReturn the global sync Store singleton, creating it on first call.\n\n    The legacy ``checkpointer`` section takes precedence when configured;\n    otherwise the unified ``database`` section selects the backend.\n\n    Raises:\n        ImportError: If the required package for the configured backend is not installed.\n        ValueError: If the selected backend is missing its required connection value.\n    '
    global _store, _store_ctx

    if _store is not None:
        return _store

    # Config loading can reset both persistence singletons. Resolve the full
    # config outside this provider lock to avoid lock-order inversion.
    config = _get_store_config()

    with _store_lock:
        if _store is not None:
            return _store

        store_ctx = _sync_store_cm(config)
        store = store_ctx.__enter__()
        _store_ctx = store_ctx
        _store = store
    return _store


def reset_store() -> None:
    '执行 reset_store 的明确职责，并返回与调用约定一致的结果。\n\nReset the sync singleton, forcing recreation on the next call.\n\n    Closes any open backend connections and clears the cached instance.\n    Useful in tests or after a configuration change.\n    '
    global _store, _store_ctx
    with _store_lock:
        if _store_ctx is not None:
            try:
                _store_ctx.__exit__(None, None, None)
            except Exception:
                logger.warning("Error during store cleanup", exc_info=True)
            _store_ctx = None
        _store = None


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def store_context() -> Iterator[BaseStore]:
    '执行 store_context 的明确职责，并返回与调用约定一致的结果。\n\nSync context manager that yields a Store and cleans up on exit.\n\n    Unlike :func:`get_store`, this does **not** cache the instance — each\n    ``with`` block creates and destroys its own connection.  Use it in CLI\n    scripts or tests where you want deterministic cleanup::\n\n        with store_context() as store:\n            store.put(("threads",), thread_id, {...})\n\n    The legacy ``checkpointer`` section takes precedence when configured;\n    otherwise the unified ``database`` section selects the backend.\n    '
    config = _resolve_store_config(get_app_config())
    with _sync_store_cm(config) as store:
        yield store
