'''提供同步 PostgreSQL 存储器的单例访问和短生命周期上下文管理器。'''

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator

from langgraph.store.base import BaseStore

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig, ensure_config_loaded, get_checkpointer_config

logger = logging.getLogger(__name__)


POSTGRES_STORE_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL store. Install the package extra with: pip install 'deer-flow[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"


def _resolve_store_config(app_config: AppConfig) -> CheckpointerConfig:
    '''优先复用旧版 checkpointer 配置；否则从统一数据库配置构造 PostgreSQL 参数。'''
    if app_config.checkpointer is not None:
        return app_config.checkpointer

    database = app_config.database
    if database is None or not database.postgres_url:
        raise ValueError("database.postgres_url is required for the postgres backend")
    return CheckpointerConfig(type="postgres", connection_string=database.postgres_url)


def _get_store_config() -> CheckpointerConfig:
    '''在获取单例锁之前解析配置，避免配置重载与存储器锁发生反向等待。'''
    ensure_config_loaded()

    legacy_config = get_checkpointer_config()
    if legacy_config is not None:
        return legacy_config
    try:
        app_config = get_app_config()
    except FileNotFoundError as exc:
        raise RuntimeError("PostgreSQL store configuration is required") from exc
    return _resolve_store_config(app_config)




@contextlib.contextmanager
def _sync_store_cm(config) -> Iterator[BaseStore]:
    '''创建并初始化同步 PostgreSQL 存储器，离开上下文时关闭连接。'''
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



_store: BaseStore | None = None
_store_ctx = None
_store_lock = threading.Lock()


def get_store() -> BaseStore:
    '''获取同步存储器单例；首次调用时按当前配置创建并保留连接上下文。'''
    global _store, _store_ctx

    if _store is not None:
        return _store

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
    '''关闭并清空同步存储器单例，使后续调用按最新配置重新创建。'''
    global _store, _store_ctx
    with _store_lock:
        if _store_ctx is not None:
            try:
                _store_ctx.__exit__(None, None, None)
            except Exception:
                logger.warning("Error during store cleanup", exc_info=True)
            _store_ctx = None
        _store = None




@contextlib.contextmanager
def store_context() -> Iterator[BaseStore]:
    '''为一次同步操作创建独立存储器；退出 ``with`` 块时关闭连接，不缓存实例。'''
    config = _resolve_store_config(get_app_config())
    with _sync_store_cm(config) as store:
        yield store
