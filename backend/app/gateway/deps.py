"""集中访问存储于 ``app.state`` 的单例对象。

供路由使用的获取器在必需依赖缺失时返回 503，唯有 ``get_store`` 可返回 ``None``。
``AppConfig`` 刻意不缓存于 ``app.state``，路由和运行路径经由支持 mtime 热重载的
``get_app_config`` 解析，使 config.yaml 修改在下一请求生效。``langgraph_runtime`` 创建的
流桥、持久化、检查点、存储及运行事件存储使用启动快照，按设计必须重启后才更新，以确保
正在运行的进程内部一致。初始化由 app.py 通过 ``AsyncExitStack`` 直接完成。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, TypeVar, cast

from fastapi import FastAPI, HTTPException, Request
from langgraph.types import Checkpointer

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.persistence.feedback import FeedbackRepository
from deerflow.runtime import RunContext, RunManager, StreamBridge
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.runs.store.base import RunStore

logger = logging.getLogger(__name__)

# 在 AsyncExitStack 销毁检查点及连接池前，关闭期间排空在途运行的最长秒数。将它保留在
# 本模块可避免 app → deps → app 的导入环。它与 app.py 的频道服务停止时限独立，两者均计入
# 生命周期关闭窗口；若总和必须受服务器优雅关闭时限约束，应一并调整。
_RUN_DRAIN_TIMEOUT_SECONDS = 5.0


def _enforce_postgres_for_multi_worker(config: AppConfig) -> None:
    """多工作进程安全前提不满足时，拒绝以 ``GATEWAY_WORKERS > 1`` 启动。

    多工作进程必须同时使用 Postgres（SQLite 写锁不支持多进程并发）并启用
    ``run_ownership.heartbeat_enabled``；否则运行均无租约，协调过程会将所有在途运行视作
    无主运行，工作进程 B 可能在滚动更新或扩容时终止工作进程 A 的存活运行。该门禁在任何
    持久化引擎初始化前仅于启动时执行一次，以便清晰报错并立即退出。
    """
    try:
        workers = int(os.environ.get("GATEWAY_WORKERS", "1"))
    except (TypeError, ValueError):
        workers = 1

    if workers <= 1:
        return

    backend = getattr(config.database, "backend", None)
    if backend != "postgres":
        raise SystemExit(f"GATEWAY_WORKERS={workers} requires database.backend='postgres', but database.backend is '{backend}'. SQLite cannot support concurrent multi-process access. Set GATEWAY_WORKERS=1 or switch to Postgres.")

    run_ownership = getattr(config, "run_ownership", None)
    if run_ownership is None or not run_ownership.heartbeat_enabled:
        raise SystemExit(
            f"GATEWAY_WORKERS={workers} requires run_ownership.heartbeat_enabled=true. "
            "Without heartbeat, every run has a NULL lease, so reconciliation "
            "treats all inflight runs as orphans — Worker B would kill Worker A's "
            "live runs on every rolling update or scale-up. "
            "Set run_ownership.heartbeat_enabled=true in config.yaml."
        )


async def _drain_inflight_runs(run_manager: RunManager) -> None:
    """在销毁检查点前排空在途运行，避免运行任务仍写入检查点时关闭其连接池。

    对有内部时限的排空操作做屏蔽；即使生命周期协程在关闭中因第二个 SIGINT 或服务器
    优雅关闭超时而被取消，也允许已启动的排空在 ``RunManager.shutdown`` 的时限内完成，
    随后再传播取消。
    """
    drain = asyncio.create_task(run_manager.shutdown(timeout=_RUN_DRAIN_TIMEOUT_SECONDS))
    try:
        await asyncio.shield(drain)
    except asyncio.CancelledError:
        # 再次屏蔽，避免第二次等待放弃在途排空；它有时限，不会卡死，随后重新抛出以遵循关闭。
        try:
            await asyncio.shield(drain)
        except Exception:
            logger.exception("In-flight run drain failed after shutdown cancellation")
        raise
    except Exception:
        logger.exception("Failed to drain in-flight runs during shutdown")


async def _publish_recovered_run_stream_end(
    bridge: StreamBridge,
    recovered_runs: list[RunRecord],
    *,
    cleanup_delay: float = 60.0,
) -> None:
    """为启动时恢复为无主状态的运行终止保留事件流。"""
    for record in recovered_runs:
        stream_exists = getattr(bridge, "stream_exists", None)
        if stream_exists is not None:
            try:
                if not await stream_exists(record.run_id):
                    logger.debug("Skipping recovered stream end for %s: stream already expired", record.run_id)
                    continue
            except Exception:
                logger.debug("Failed to check recovered stream existence for %s", record.run_id, exc_info=True)
        try:
            await bridge.publish_end(record.run_id)
        except Exception:
            logger.warning(
                "Failed to publish recovered run stream end for %s",
                record.run_id,
                exc_info=True,
            )
            continue
        task = asyncio.create_task(bridge.cleanup(record.run_id, delay=cleanup_delay))
        task.add_done_callback(lambda task, run_id=record.run_id: _log_recovered_stream_cleanup_result(task, run_id))


def _log_recovered_stream_cleanup_result(task: asyncio.Task[None], run_id: str) -> None:
    """记录恢复运行的延迟事件流清理任务异常，取消任务无需额外处理。"""
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.warning("Failed to clean up recovered run stream for %s", run_id, exc_info=True)


if TYPE_CHECKING:
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.thread_meta.base import ThreadMetaStore
    from deerflow.runtime import RunRecord


T = TypeVar("T")


async def _mark_latest_recovered_threads_error(
    run_manager: RunManager,
    thread_store: ThreadMetaStore,
    recovered_runs: list[RunRecord],
) -> None:
    """仅当线程最新运行被恢复时才将其状态标记为错误。"""
    recovered_by_thread: dict[str, set[str]] = {}
    for record in recovered_runs:
        recovered_by_thread.setdefault(record.thread_id, set()).add(record.run_id)

    for thread_id, recovered_run_ids in recovered_by_thread.items():
        try:
            latest_runs = await run_manager.list_by_thread(thread_id, user_id=None, limit=1)
        except Exception:
            logger.warning("Failed to find latest run for thread %s during run reconciliation", thread_id, exc_info=True)
            continue
        if not latest_runs or latest_runs[0].run_id not in recovered_run_ids:
            continue
        try:
            await thread_store.update_status(thread_id, "error", user_id=None)
        except Exception:
            logger.warning("Failed to mark thread %s as error during run reconciliation", thread_id, exc_info=True)


def get_config() -> AppConfig:
    """返回当前请求的最新 ``AppConfig``。

    Routes through :func:`deerflow.config.app_config.get_app_config`, which
    honours runtime ``ContextVar`` overrides and reloads ``config.yaml`` from
    disk when its mtime changes. ``AppConfig`` is not cached on ``app.state``
    at all — the only startup-time snapshot lives as a local
    ``startup_config`` variable inside ``lifespan()`` and is passed
    explicitly into :func:`langgraph_runtime` for the engines that are
    restart-required by design. Routing every request through
    :func:`get_app_config` closes the bytedance/deer-flow issue #3107 BUG-001
    split-brain where the worker / lead-agent thread saw a stale startup
    snapshot.

    Hot-reload boundary: fields backed by startup-time singletons
    (engines, sandbox provider, IM channels, logging handler) require a
    process restart to change at runtime. The authoritative list lives in
    :mod:`deerflow.config.reload_boundary` and is mirrored by the
    standardised ``"startup-only:"`` prefix on the matching
    ``Field(description=...)`` in :class:`AppConfig` — IDE hover on those
    fields will surface the boundary inline. See
     ``backend/AGENTS.md`` "Config Hot-Reload Boundary" for the operator
    summary.

    Any failure to materialise the config (missing file, permission denied,
    YAML parse error, validation error) is reported as 503 — semantically
    "the gateway cannot serve requests without a usable configuration" — and
    logged with the original exception so operators have something to debug.
    """
    try:
        return get_app_config()
    except Exception as exc:  # noqa: BLE001 - 请求边界：记录日志并优雅降级。
        logger.exception("Failed to load AppConfig at request time")
        raise HTTPException(status_code=503, detail="Configuration not available") from exc


@asynccontextmanager
async def langgraph_runtime(app: FastAPI, startup_config: AppConfig) -> AsyncGenerator[None, None]:
    """引导并销毁所有 LangGraph 运行时单例。

    ``startup_config`` is the ``AppConfig`` snapshot taken once during
    ``lifespan()`` for one-shot infrastructure bootstrap. The engines and
    stores constructed here (stream bridge, persistence engine, checkpointer,
    store, run-event store) are restart-required by design — they hold live
    connections, file handles, or singleton providers — so they bind to this
    snapshot and survive across `config.yaml` edits. Request-time consumers
    must still go through :func:`get_config` for any field that should be
     hot-reloadable. See ``backend/AGENTS.md`` "Config Hot-Reload Boundary".

    The matching ``run_events_config`` is frozen onto ``app.state`` so
    :func:`get_run_context` pairs a freshly-loaded ``AppConfig`` with the
    *startup-time* run-events configuration the underlying ``event_store``
    was built from — otherwise the runtime could end up combining a live
    new ``run_events_config`` with an event store still bound to the
    previous backend.

    Usage in ``app.py``::

        async with langgraph_runtime(app, startup_config):
            yield
    """
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.runtime import make_store, make_stream_bridge
    from deerflow.runtime.checkpointer.async_provider import make_checkpointer
    from deerflow.runtime.events.store import make_run_event_store

    # ------------------------------------------------------------------
    # 多工作进程安全门禁：GATEWAY_WORKERS > 1 时拒绝 SQLite，其写锁不支持多进程并发。
    # ------------------------------------------------------------------
    _enforce_postgres_for_multi_worker(startup_config)

    async with AsyncExitStack() as stack:
        config = startup_config

        app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge(config))

        # 在检查点前初始化持久化引擎，使数据库自动创建逻辑优先运行（Postgres 后端）。
        await init_engine_from_config(config.database)

        app.state.checkpointer = await stack.enter_async_context(make_checkpointer(config))
        app.state.store = await stack.enter_async_context(make_store(config))

        # 初始化仓库，所有仓库共用一次 get_session_factory() 调用。
        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("Database persistence is unavailable; configure database.backend as sqlite or postgres.")

        from deerflow.persistence.feedback import FeedbackRepository
        from deerflow.persistence.run import RunRepository

        app.state.run_store = RunRepository(sf)
        app.state.feedback_repo = FeedbackRepository(sf)

        from deerflow.persistence.thread_meta import make_thread_store

        app.state.thread_store = make_thread_store(sf)
        from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
        from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

        app.state.scheduled_task_repo = ScheduledTaskRepository(sf)
        app.state.scheduled_task_run_repo = ScheduledTaskRunRepository(sf)

        # 运行事件存储及配套 ``run_events_config`` 都在启动时冻结，避免 get_run_context
        # 将刚重载的 AppConfig.run_events 与仍绑定旧后端的存储组合。
        run_events_config = getattr(config, "run_events", None)
        app.state.run_events_config = run_events_config
        app.state.run_event_store = make_run_event_store(run_events_config)

        # 使用存储作为持久化后端的 RunManager。
        run_ownership_config = getattr(config, "run_ownership", None)
        app.state.run_manager = RunManager(
            store=app.state.run_store,
            run_ownership_config=run_ownership_config,
        )
        # 启动恢复：将租约已过期的在途运行标记为错误。单工作进程模式（SQLite / memory）
        # 中运行没有租约，故回收所有在途行；多工作进程模式（Postgres）只回收租约过期的
        # 运行，并跳过归属其他存活工作进程的运行。
        from deerflow.utils.time import now_iso

        recovered_runs = await app.state.run_manager.reconcile_orphaned_inflight_runs(
            error="Gateway restarted before this run reached a durable final state.",
            before=now_iso(),
        )
        sb_config = getattr(config, "stream_bridge", None)
        cleanup_delay = getattr(sb_config, "recovered_stream_cleanup_delay_seconds", 60.0) if sb_config else 60.0
        await _publish_recovered_run_stream_end(app.state.stream_bridge, recovered_runs, cleanup_delay=cleanup_delay)
        await _mark_latest_recovered_threads_error(app.state.run_manager, app.state.thread_store, recovered_runs)

        # 多工作进程部署中若启用则启动租约心跳。
        await app.state.run_manager.start_heartbeat()

        try:
            yield
        finally:
            # 在 AsyncExitStack 销毁检查点及连接池前排空在途运行任务；否则尚在图中执行的
            # 运行会泄漏至 asyncio.run() 关闭阶段，与已关闭连接池竞争并引发 PoolClosed。
            run_manager = getattr(app.state, "run_manager", None)
            if run_manager is not None:
                await _drain_inflight_runs(run_manager)
            await close_engine()


# ---------------------------------------------------------------------------
# 供路由按请求调用的获取器。
# ---------------------------------------------------------------------------


def _require(attr: str, label: str) -> Callable[[Request], T]:
    """创建返回 ``app.state.<attr>`` 的 FastAPI 依赖；缺失时返回 503。"""

    def dep(request: Request) -> T:
        """从应用状态读取已初始化依赖；缺失时向当前请求返回 503。"""
        val = getattr(request.app.state, attr, None)
        if val is None:
            raise HTTPException(status_code=503, detail=f"{label} not available")
        return cast(T, val)

    dep.__name__ = dep.__qualname__ = f"get_{attr}"
    return dep


get_stream_bridge: Callable[[Request], StreamBridge] = _require("stream_bridge", "Stream bridge")
get_run_manager: Callable[[Request], RunManager] = _require("run_manager", "Run manager")
get_checkpointer: Callable[[Request], Checkpointer] = _require("checkpointer", "Checkpointer")
get_run_event_store: Callable[[Request], RunEventStore] = _require("run_event_store", "Run event store")
get_feedback_repo: Callable[[Request], FeedbackRepository] = _require("feedback_repo", "Feedback")
get_run_store: Callable[[Request], RunStore] = _require("run_store", "Run store")


def get_store(request: Request):
    """返回全局存储；未配置时可能为 ``None``。"""
    return getattr(request.app.state, "store", None)


def get_thread_store(request: Request) -> ThreadMetaStore:
    """返回线程元数据存储，可由 SQL 或内存后端支撑。"""
    val = getattr(request.app.state, "thread_store", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Thread metadata store not available")
    return val


def get_scheduled_task_repo(request: Request):
    """返回调度任务持久化仓库，供路由在当前应用生命周期内访问。"""
    val = getattr(request.app.state, "scheduled_task_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task repo not available")
    return val


def get_scheduled_task_run_repo(request: Request):
    """返回调度任务运行记录仓库，保留执行历史的持久化边界。"""
    val = getattr(request.app.state, "scheduled_task_run_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task run repo not available")
    return val


def get_scheduled_task_service(request: Request):
    """返回已初始化的调度服务，用于创建、变更和触发后台任务。"""
    val = getattr(request.app.state, "scheduled_task_service", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task service not available")
    return val


def get_run_context(request: Request) -> RunContext:
    """从 ``app.state`` 单例构建 :class:`RunContext`。

    Returns a *base* context with infrastructure dependencies. The
    ``app_config`` field is resolved live so per-run fields (e.g.
    ``models[*].max_tokens``) follow ``config.yaml`` edits; the
    ``event_store`` / ``run_events_config`` pair stays frozen to the snapshot
    captured in :func:`langgraph_runtime` so callers never see a store bound
    to one backend paired with a config pointing at another.
    """
    return RunContext(
        checkpointer=get_checkpointer(request),
        store=get_store(request),
        event_store=get_run_event_store(request),
        run_events_config=getattr(request.app.state, "run_events_config", None),
        thread_store=get_thread_store(request),
        app_config=get_config(),
        on_run_completed=getattr(request.app.state, "scheduled_task_service", None).handle_run_completion if getattr(request.app.state, "scheduled_task_service", None) is not None else None,
    )


# ---------------------------------------------------------------------------
# 认证辅助函数，供 authz.py 与认证中间件使用。
# ---------------------------------------------------------------------------

# 缓存单例，避免每个请求重复实例化。
_cached_local_provider: LocalAuthProvider | None = None
_cached_repo: SQLiteUserRepository | None = None


def get_local_provider() -> LocalAuthProvider:
    """获取或创建缓存的 LocalAuthProvider 单例。

    Must be called after ``init_engine_from_config()`` — the shared
    session factory is required to construct the user repository.
    """
    global _cached_local_provider, _cached_repo
    if _cached_repo is None:
        from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
        from deerflow.persistence.engine import get_session_factory

        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("get_local_provider() called before init_engine_from_config(); cannot access users table")
        _cached_repo = SQLiteUserRepository(sf)
    if _cached_local_provider is None:
        from app.gateway.auth.local_provider import LocalAuthProvider

        _cached_local_provider = LocalAuthProvider(repository=_cached_repo)
    return _cached_local_provider


async def get_current_user_from_request(request: Request):
    """从请求 Cookie 获取当前已认证用户。

    Raises HTTPException 401 if not authenticated.
    """
    state = getattr(request, "state", None)
    state_user = getattr(state, "user", None)
    from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION

    if state_user is not None and getattr(state, "auth_source", None) in {
        AUTH_SOURCE_SESSION,
        AUTH_SOURCE_AUTH_DISABLED,
        AUTH_SOURCE_INTERNAL,
    }:
        return state_user

    from app.gateway.auth import decode_token
    from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError, token_error_to_code

    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.NOT_AUTHENTICATED, message="Not authenticated").model_dump(),
        )

    payload = decode_token(access_token)
    if isinstance(payload, TokenError):
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=token_error_to_code(payload), message=f"Token error: {payload.value}").model_dump(),
        )

    provider = get_local_provider()
    user = await provider.get_user(payload.sub)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.USER_NOT_FOUND, message="User not found").model_dump(),
        )

    # 令牌版本不匹配表示密码已变更，令牌已过期。
    if user.token_version != payload.ver:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.TOKEN_INVALID, message="Token revoked (password changed)").model_dump(),
        )

    return user


async def require_admin_user(request: Request, *, detail: str) -> None:
    """要求已认证调用方为管理员用户。

    ``AuthMiddleware`` normally stamps ``request.state.user`` before the request
    reaches a router. Falling back to the strict dependency keeps the route safe
    in tests or alternative ASGI compositions that mount a router without the
    global middleware. ``detail`` is the route-specific 403 message.

    Centralising this here means a future change to the admin definition (e.g.
    allowing an internal system role, adding audit logging, or switching to a
    permission-based check) lands in one place instead of drifting across the
    per-router copies that previously existed in ``mcp``, ``channel_connections``
    and ``channels``.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        user = await get_current_user_from_request(request)

    if getattr(user, "system_role", None) != "admin":
        raise HTTPException(status_code=403, detail=detail)


async def get_optional_user_from_request(request: Request):
    """从请求获取可选的已认证用户。

    Returns None if not authenticated.
    """
    try:
        return await get_current_user_from_request(request)
    except HTTPException:
        return None


async def get_current_user(request: Request) -> str | None:
    """从请求 Cookie 提取 user_id；未认证时返回 None。

    Thin adapter that returns the string id for callers that only need
    identification (e.g., ``feedback.py``). Full-user callers should use
    ``get_current_user_from_request`` or ``get_optional_user_from_request``.
    """
    user = await get_optional_user_from_request(request)
    return str(user.id) if user else None
