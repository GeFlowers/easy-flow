"""

Sync checkpointer factory.

Provides a **sync singleton** and a **sync context manager** for LangGraph
graph compilation and CLI tools.

Supported database backend: PostgreSQL. The legacy standalone
``checkpointer`` configuration may still provide the PostgreSQL DSN.

Usage::

    from deerflow.runtime.checkpointer.provider import get_checkpointer, checkpointer_context

    # Singleton — reused across calls, closed on process exit
    cp = get_checkpointer()

    # One-shot — fresh connection, closed on block exit
    with checkpointer_context() as cp:
        graph.invoke(input, config={"configurable": {"thread_id": "1"}})
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig, ensure_config_loaded, get_checkpointer_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error message constants — imported by aio.provider too
# ---------------------------------------------------------------------------

POSTGRES_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install the package extra with: pip install 'deerflow-harness[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def _resolve_checkpointer_config(app_config: AppConfig) -> CheckpointerConfig:
    """

    解析：the checkpointer backend from legacy or unified application config.

        The legacy ``checkpointer`` section remains authoritative when present so
        Checkpointer and Store keep using the same backend. Otherwise the unified
        ``database`` section drives the checkpointer, matching the async
        :func:`~deerflow.runtime.checkpointer.async_provider.make_checkpointer`
        factory and the sync Store provider's ``_resolve_store_config``.
    """
    if app_config.checkpointer is not None:
        return app_config.checkpointer

    database = app_config.database
    if database is None or not database.postgres_url:
        raise ValueError("database.postgres_url is required for the postgres backend")
    return CheckpointerConfig(type="postgres", connection_string=database.postgres_url)


def _get_checkpointer_config() -> CheckpointerConfig:
    """

    加载：checkpointer config without holding the provider singleton lock."""
    ensure_config_loaded()

    # Preserve callers that initialise the legacy config singleton directly.
    legacy_config = get_checkpointer_config()
    if legacy_config is not None:
        return legacy_config
    try:
        app_config = get_app_config()
    except FileNotFoundError as exc:
        raise RuntimeError("PostgreSQL checkpointer configuration is required") from exc
    return _resolve_checkpointer_config(app_config)


# ---------------------------------------------------------------------------
# Sync factory
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _sync_checkpointer_cm(config: CheckpointerConfig) -> Iterator[Checkpointer]:
    """

    创建同步 PostgreSQL 检查点器并在上下文结束时关闭连接。

        Returns a configured ``Checkpointer`` instance. Resource cleanup for any
        underlying connections or pools is handled by higher-level helpers in
        this module (such as the singleton factory or context manager); this
        function does not return a separate cleanup callback.
    """
    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        with PostgresSaver.from_conn_string(config.connection_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_checkpointer: Checkpointer | None = None
_checkpointer_ctx = None  # open context manager keeping the connection alive
_checkpointer_lock = threading.Lock()


def get_checkpointer() -> Checkpointer:
    """

    返回：the global sync checkpointer singleton, creating it on first call.

        The legacy ``checkpointer`` section takes precedence when configured;
        otherwise the unified PostgreSQL ``database`` section selects the backend.

        Raises:
            ImportError: If the required package for the configured backend is not installed.
            ValueError: If ``connection_string`` is missing for a backend that requires it.
    """
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    # Config loading can reset both persistence singletons. Resolve the full
    # config outside this provider lock to avoid cross-provider lock-order inversion.
    config = _get_checkpointer_config()

    with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer

        checkpointer_ctx = _sync_checkpointer_cm(config)
        checkpointer = checkpointer_ctx.__enter__()
        _checkpointer_ctx = checkpointer_ctx
        _checkpointer = checkpointer

    return _checkpointer


def reset_checkpointer() -> None:
    """

    重置：the sync singleton, forcing recreation on the next call.

        Closes any open backend connections and clears the cached instance.
        Useful in tests or after a configuration change.
    """
    global _checkpointer, _checkpointer_ctx
    with _checkpointer_lock:
        if _checkpointer_ctx is not None:
            try:
                _checkpointer_ctx.__exit__(None, None, None)
            except Exception:
                logger.warning("Error during checkpointer cleanup", exc_info=True)
            _checkpointer_ctx = None
        _checkpointer = None


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def checkpointer_context() -> Iterator[Checkpointer]:
    """

    同步上下文管理器： that yields a checkpointer and cleans up on exit.

        Unlike :func:`get_checkpointer`, this does **not** cache the instance —
        each ``with`` block creates and destroys its own connection.  Use it in
        CLI scripts or tests where you want deterministic cleanup::

            with checkpointer_context() as cp:
                graph.invoke(input, config={"configurable": {"thread_id": "1"}})

        The legacy ``checkpointer`` section takes precedence when configured;
        otherwise the unified PostgreSQL ``database`` section selects the backend.
    """

    config = _resolve_checkpointer_config(get_app_config())
    with _sync_checkpointer_cm(config) as saver:
        yield saver
