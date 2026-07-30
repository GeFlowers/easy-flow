"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

import asyncio
import logging
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


# Where the alembic environment lives, relative to this file.
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Cached migration head, computed once per process from the disk script tree.
_HEAD_REVISION: str | None = None

# Baseline (stamp target for legacy DBs). Pinned here so the bootstrap layer
# fails loudly if the baseline revision is ever renamed without updating the
# stamp call. ``tests/test_persistence_bootstrap.py`` asserts this string is a
# real revision id in the script tree.
_BASELINE_REVISION = "0001_baseline"

# Stable advisory-lock key for Postgres. Two random 32-bit halves picked once
# so we never collide with any other application's advisory locks. Do not
# change without coordinating a one-time migration (a key change effectively
# releases the prior lock).
_PG_LOCK_KEY = 0x0DEE_12F1_0BEE_3682


# Tables created by ``0001_baseline.upgrade()``. The legacy branch restricts
# its ``create_all`` backfill to this set so it does NOT pre-empt later
# ``op.create_table`` revisions for models added after baseline -- those
# revisions would otherwise fail with ``relation already exists`` if
# ``create_all`` had created their table first. (Column revisions are
# already safe via the idempotent helpers in ``migrations/_helpers.py``;
# there is no analogous ``safe_create_table`` yet, so we keep table-level
# safety at this layer instead of pushing it onto every future revision.)
#
# ``test_baseline_table_names_constant_matches_0001`` pins this set against
# what 0001 actually creates -- editing 0001 without updating this constant
# (or vice versa) fires that test.
_BASELINE_TABLE_NAMES: frozenset[str] = frozenset(
    {
        "channel_connections",
        "channel_conversations",
        "channel_credentials",
        "channel_oauth_states",
        "feedback",
        "run_events",
        "runs",
        "threads_meta",
        "users",
    }
)

# ``test_baseline_index_names_constant_matches_0001`` pins this set against
# what 0001 actually creates -- editing 0001 without updating this constant
# (or vice versa) fires that test.
_BASELINE_INDEX_NAMES: frozenset[str] = frozenset(
    {
        # channel_connections
        "idx_channel_connections_event_lookup",
        "ix_channel_connections_owner_user_id",
        "ix_channel_connections_provider",
        "uq_channel_connection_active_identity",
        # channel_conversations
        "ix_channel_conversations_connection_id",
        "ix_channel_conversations_owner_user_id",
        "ix_channel_conversations_provider",
        "ix_channel_conversations_thread_id",
        # channel_oauth_states
        "ix_channel_oauth_states_owner_user_id",
        "ix_channel_oauth_states_provider",
        # feedback
        "ix_feedback_run_id",
        "ix_feedback_thread_id",
        "ix_feedback_user_id",
        # run_events
        "ix_events_run",
        "ix_events_thread_cat_seq",
        "ix_run_events_user_id",
        # runs
        "ix_runs_thread_id",
        "ix_runs_thread_status",
        "ix_runs_user_id",
        # threads_meta
        "ix_threads_meta_assistant_id",
        "ix_threads_meta_user_id",
        # users
        "idx_users_oauth_identity",
        "ix_users_email",
    }
)


# Per-engine SQLite bootstrap locks. Per-engine (not module-global) so each
# engine instance pairs with a lock bound to the event loop that uses that
# engine -- necessary because ``asyncio.Lock`` binds to the first loop it sees,
# and pytest gives each async test its own loop. Production uses one engine
# per process so this dict collapses to a single entry in practice.
#
# Keyed by the engine object itself via ``WeakKeyDictionary`` rather than
# ``id(engine)``: CPython recycles addresses after GC, so a stale ``id`` →
# ``Lock`` entry from a dead engine could be returned to a new engine that
# happened to land on the same address. The returned lock would still be bound
# to the dead engine's event loop and ``async with`` would raise
# ``RuntimeError: ... bound to a different event loop``. Hashing the engine
# itself also drops entries automatically when the engine is collected, so this
# dict never grows past the live engine count.
_SQLITE_LOCKS: weakref.WeakKeyDictionary[AsyncEngine, asyncio.Lock] = weakref.WeakKeyDictionary()


def _get_sqlite_local_lock(engine: AsyncEngine) -> asyncio.Lock:
    """获取并管理数据库架构操作所需的并发互斥锁。"""
    lock = _SQLITE_LOCKS.get(engine)
    if lock is None:
        lock = asyncio.Lock()
        _SQLITE_LOCKS[engine] = lock
    return lock


def _escape_url_for_alembic(url: str) -> str:
    """执行持久化流程所需的内部辅助操作。"""
    return url.replace("%", "%%")


def _alembic_safe_url(engine: AsyncEngine) -> str:
    """执行持久化流程所需的内部辅助操作。"""
    rendered = engine.url.render_as_string(hide_password=False)
    return _escape_url_for_alembic(rendered)


def _get_alembic_config(engine: AsyncEngine) -> AlembicConfig:
    """执行持久化流程所需的内部辅助操作。"""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _alembic_safe_url(engine))
    return cfg


def _get_head_revision() -> str:
    """执行持久化流程所需的内部辅助操作。"""
    global _HEAD_REVISION
    if _HEAD_REVISION is None:
        cfg = AlembicConfig()
        cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        if head is None:
            raise RuntimeError("alembic has no head revision -- versions/ directory is empty")
        _HEAD_REVISION = head
    return _HEAD_REVISION


def _reflect_state(sync_conn: Any) -> dict[str, bool]:
    """执行持久化流程所需的内部辅助操作。"""
    from deerflow.persistence.base import Base

    # Make sure every ORM model is imported, otherwise ``Base.metadata.tables``
    # may miss tables registered by submodules that haven't been imported yet.
    try:
        import deerflow.persistence.models  # noqa: F401
    except ImportError:
        logger.debug("deerflow.persistence.models not found; metadata may be incomplete")

    insp = sa_inspect(sync_conn)
    reflected = set(insp.get_table_names())
    metadata_tables = set(Base.metadata.tables)
    return {
        "has_alembic_version": "alembic_version" in reflected,
        "has_deerflow_tables": bool(reflected & metadata_tables),
    }


def _decide_state(state: dict[str, bool]) -> str:
    """执行持久化流程所需的内部辅助操作。"""
    if state["has_alembic_version"]:
        return "versioned"
    if not state["has_deerflow_tables"]:
        # Either a brand-new DB or a DB containing only tables we don't own
        # (e.g. LangGraph's checkpointer tables on a fresh deployment). The
        # empty branch provisions the tables alembic owns, then stamps head.
        return "empty"
    return "legacy"


def _run_create_all_sync(sync_conn: Any) -> None:
    """执行持久化流程所需的内部辅助操作。"""
    # Import here to ensure all model classes are registered with Base.metadata.
    from deerflow.persistence.base import Base

    try:
        import deerflow.persistence.models  # noqa: F401
    except ImportError:
        logger.debug("deerflow.persistence.models not found; bootstrap will create empty schema")

    Base.metadata.create_all(sync_conn)


def _run_baseline_create_all_sync(sync_conn: Any) -> None:
    """执行持久化流程所需的内部辅助操作。"""
    from deerflow.persistence.base import Base

    try:
        import deerflow.persistence.models  # noqa: F401
    except ImportError:
        logger.debug("deerflow.persistence.models not found; baseline backfill may be incomplete")

    baseline_tables = [Base.metadata.tables[name] for name in _BASELINE_TABLE_NAMES if name in Base.metadata.tables]
    Base.metadata.create_all(sync_conn, tables=baseline_tables, checkfirst=True)

    # ``create_all`` with ``checkfirst=True`` skips a table and all its
    # subordinate ``Index`` objects when the table already exists.  An index
    # that was added to the ORM model after the table was first provisioned
    # would therefore never be created, and because the legacy branch stamps
    # ``0001_baseline`` before running upgrade, alembic's own
    # ``batch_op.create_index`` for baseline-era indexes is skipped too.
    # Explicitly creating every baseline-era ``Index`` on every baseline table
    # (each with its own ``checkfirst=True``) guarantees each index exists
    # regardless of whether its parent table was just created or already
    # present.
    #
    # **Scope**: Only indexes in ``_BASELINE_INDEX_NAMES`` are created.
    # ``table.indexes`` is the *current* ORM model's full index set, which
    # includes post-baseline indexes added by later revisions (e.g.
    # ``uq_runs_thread_active`` from 0004).  Creating those prematurely would
    # collide with their owning revision's data prerequisites (dedup steps,
    # column migrations) and raise ``IntegrityError`` on legacy DBs.
    #
    # Post-baseline revisions that add an index to a baseline table must use
    # the existing ``sa.inspect(bind).get_indexes(...)`` + ``if name not in
    # existing`` guard pattern (see 0004_run_ownership.py:99-103), or a future
    # ``safe_create_index`` helper -- mirroring ``safe_add_column``.
    for table in baseline_tables:
        for idx in table.indexes:
            if idx.name not in _BASELINE_INDEX_NAMES:
                continue
            try:
                idx.create(sync_conn, checkfirst=True)
            except Exception:
                logger.warning(
                    "bootstrap: failed to create baseline index %r on %r -- the DB may contain rows that violate the index constraint. Address the duplicate data, then re-run bootstrap.",
                    idx.name,
                    table.name,
                )


def _stamp(cfg: AlembicConfig, revision: str) -> None:
    """执行持久化流程所需的内部辅助操作。"""
    alembic_command.stamp(cfg, revision)


def _upgrade(cfg: AlembicConfig, revision: str) -> None:
    """执行持久化流程所需的内部辅助操作。"""
    alembic_command.upgrade(cfg, revision)


# ---------------------------------------------------------------------------
# Cross-process locking
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _postgres_lock(engine: AsyncEngine):
    """获取并管理数据库架构操作所需的并发互斥锁。"""
    async with engine.connect() as conn:
        await conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _PG_LOCK_KEY})
        try:
            logger.info("bootstrap: acquired postgres advisory lock key=0x%x", _PG_LOCK_KEY)
            yield
        finally:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _PG_LOCK_KEY})
            except Exception:  # noqa: BLE001
                logger.warning("bootstrap: pg_advisory_unlock raised; session close will release", exc_info=True)


@asynccontextmanager
async def _sqlite_lock(engine: AsyncEngine):
    """获取并管理数据库架构操作所需的并发互斥锁。"""
    async with _get_sqlite_local_lock(engine):
        logger.info("bootstrap: acquired sqlite in-process lock")
        yield


def _bootstrap_lock(engine: AsyncEngine, *, backend: str):
    """获取并管理数据库架构操作所需的并发互斥锁。"""
    if backend == "postgres":
        return _postgres_lock(engine)
    if backend == "sqlite":
        return _sqlite_lock(engine)
    raise ValueError(f"bootstrap: unsupported backend {backend!r}")


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def bootstrap_schema(engine: AsyncEngine, *, backend: str) -> None:
    """将数据库架构引导或迁移到当前目标版本。"""
    head = _get_head_revision()
    cfg = _get_alembic_config(engine)

    async with _bootstrap_lock(engine, backend=backend):
        async with engine.connect() as conn:
            state = await conn.run_sync(_reflect_state)
        decision = _decide_state(state)

        if decision == "empty":
            logger.info("bootstrap: branch=empty -> create_all + stamp head (%s)", head)
            async with engine.begin() as conn:
                await conn.run_sync(_run_create_all_sync)
            await asyncio.to_thread(_stamp, cfg, head)

        elif decision == "legacy":
            logger.info(
                "bootstrap: branch=legacy -> create_all (backfill missing baseline tables) + stamp %s + upgrade head (%s)",
                _BASELINE_REVISION,
                head,
            )
            # ``_run_baseline_create_all_sync`` is restricted to
            # ``_BASELINE_TABLE_NAMES`` -- a plain ``Base.metadata.create_all``
            # would also create tables introduced by later revisions and
            # collide with their ``op.create_table`` on the subsequent
            # upgrade. With the restriction, missing baseline tables are
            # backfilled and post-baseline ``create_table`` revisions run
            # against a DB where their tables genuinely do not yet exist.
            # The post-create_all column-add revisions still no-op via
            # ``safe_add_column`` because baseline-era tables now have the
            # columns those revisions would add.
            async with engine.begin() as conn:
                await conn.run_sync(_run_baseline_create_all_sync)
            await asyncio.to_thread(_stamp, cfg, _BASELINE_REVISION)
            await asyncio.to_thread(_upgrade, cfg, "head")

        elif decision == "versioned":
            logger.info("bootstrap: branch=versioned -> upgrade head (%s)", head)
            await asyncio.to_thread(_upgrade, cfg, "head")

        else:  # pragma: no cover -- defensive
            raise RuntimeError(f"bootstrap: unhandled decision {decision!r}")

    logger.info("bootstrap: complete (backend=%s)", backend)
