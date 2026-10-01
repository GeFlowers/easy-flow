'''组装 DeerFlow 网关的 HTTP 入口、运行时依赖和受控应用生命周期。'''

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.gateway.auth_disabled import warn_if_auth_disabled_enabled
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.config import get_gateway_config
from app.gateway.csrf_middleware import CSRFMiddleware, get_configured_cors_origins
from app.gateway.deps import langgraph_runtime
from app.gateway.routers import (
    agents,
    artifacts,
    assistants_compat,
    auth,
    channel_connections,
    channels,
    console,
    features,
    feedback,
    input_polish,
    mcp,
    memory,
    models,
    runs,
    scheduled_tasks,
    skills,
    suggestions,
    thread_runs,
    threads,
    uploads,
)
from app.gateway.trace_middleware import TraceMiddleware, resolve_trace_enabled
from deerflow.config import app_config as deerflow_app_config
from deerflow.logging_config import DEFAULT_LOG_DATE_FORMAT, DEFAULT_LOG_FORMAT, configure_logging
from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled
from deerflow.uploads.manager import cleanup_stale_upload_staging_files

AppConfig = deerflow_app_config.AppConfig
get_app_config = deerflow_app_config.get_app_config

# 默认日志配置；生命周期会使用 config.yaml 中的日志级别覆盖它。
logging.basicConfig(
    level=logging.INFO,
    format=DEFAULT_LOG_FORMAT,
    datefmt=DEFAULT_LOG_DATE_FORMAT,
)

logger = logging.getLogger(__name__)

# 每个生命周期关闭钩子允许执行的最长秒数。
# 限制工作进程退出时间，避免 uvicorn 的重载管理器持续向卡在关闭清理等待中的
# 工作进程发送信号。
_SHUTDOWN_HOOK_TIMEOUT_SECONDS = 5.0


async def _ensure_admin_user(app: FastAPI) -> None:
    '''处理首次启动，或在后续启动时迁移无主线程。

    创建管理员后，会将 LangGraph 存储中 ``metadata.user_id`` 未设置的无主线程迁移
    至该管理员账户。这是“无认证 → 启用认证”的升级路径：此前未启用认证的 DeerFlow
    用户已有需要分配所有者的 LangGraph 线程数据。

    首次启动（尚无管理员）时不自动创建用户，操作员必须访问 ``/setup`` 创建首个
    管理员。后续启动（已有管理员）时，才对无 ``user_id`` 的既有 LangGraph 线程元数据
    执行一次无主线程迁移。

    无需 SQL 持久化迁移：``threads_meta``、``runs``、``run_events`` 与 ``feedback``
    的四个 ``user_id`` 列随认证模块通过 ``create_all`` 一同创建，因此新建表不会包含
    所有者为空的行。
    '''
    from sqlalchemy import select

    from app.gateway.deps import get_local_provider
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.user.model import UserRow

    try:
        provider = get_local_provider()
    except RuntimeError:
        # 某些测试或启动路径可能尚未初始化认证持久化。
        # 跳过管理员迁移工作，避免网关启动失败。
        logger.warning("Auth persistence not ready; skipping admin bootstrap check")
        return

    sf = get_session_factory()
    if sf is None:
        return

    admin_count = await provider.count_admin_users()

    if admin_count == 0:
        logger.info("=" * 60)
        logger.info("  First boot detected — no admin account exists.")
        logger.info("  Visit /setup to complete admin account creation.")
        logger.info("=" * 60)
        return

    # 管理员已存在，迁移早于认证模块的所有 LangGraph 无主线程元数据。
    async with sf() as session:
        stmt = select(UserRow).where(UserRow.system_role == "admin").limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        return  # 上方 admin_count 已大于 0，此情况不应发生，但仍安全退出。

    admin_id = str(row.id)

    # LangGraph 存储的无主线程迁移为非致命操作，覆盖未设 user_id 的既有线程在
    # “无认证 → 启用认证”升级路径中的归属补全。
    store = getattr(app.state, "store", None)
    if store is not None:
        try:
            migrated = await _migrate_orphaned_threads(store, admin_id)
            if migrated:
                logger.info("Migrated %d orphan LangGraph thread(s) to admin", migrated)
        except Exception:
            logger.exception("LangGraph thread migration failed (non-fatal)")


async def _iter_store_items(store, namespace, *, page_size: int = 500):
    '''以分页方式异步遍历 LangGraph 存储命名空间。

    使用游标式循环取代旧的固定 ``limit=1000`` 调用，防止无主线程超过一页时静默
    丢失数据；当页面为空或取得短页（代表最后一页）时结束遍历。
    '''
    offset = 0
    while True:
        batch = await store.asearch(namespace, limit=page_size, offset=offset)
        if not batch:
            return
        for item in batch:
            yield item
        if len(batch) < page_size:
            return
        offset += page_size


async def _migrate_orphaned_threads(store, admin_user_id: str) -> int:
    '''将未设 ``user_id`` 的 LangGraph 存储线程迁移至指定管理员。

    使用游标分页确保无论无主线程数量多少都能全部迁移，并返回已迁移的行数。
    '''
    migrated = 0
    async for item in _iter_store_items(store, ("threads",)):
        metadata = item.value.get("metadata", {})
        if not metadata.get("user_id"):
            metadata["user_id"] = admin_user_id
            item.value["metadata"] = metadata
            await store.aput(("threads",), item.key, item.value)
            migrated += 1
    return migrated


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    '''管理应用启动、运行期依赖装配及受控关闭的生命周期。'''

    # 启动时加载配置并检查必要的环境变量。
    # ``startup_config`` 只是用于一次性引导工作的本地快照（日志级别、
    # langgraph_runtime 引擎和频道）。请求期配置始终通过
    # ``app/gateway/deps.py::get_config()`` 中的 ``get_app_config()`` 解析，
    # 使 config.yaml 的修改无需重启即可生效。刻意不将该快照缓存到 ``app.state``，
    # 以确保此约定可被落实。
    try:
        startup_config = get_app_config()
        configure_logging(startup_config)
        logger.info("Configuration loaded successfully")
        warn_if_auth_disabled_enabled()
    except Exception as e:
        error_msg = f"Failed to load configuration during gateway startup: {e}"
        logger.exception(error_msg)
        raise RuntimeError(error_msg) from e
    config = get_gateway_config()
    logger.info(f"Starting API Gateway on {config.host}:{config.port}")

    # 智能体可观测性（Monocle）默认关闭，通过 MONOCLE_TRACING 启用。仅在此处启动时
    # 初始化，而非导入时初始化，因此普通的 ``import deerflow.agents`` 不会安装进程级
    # 追踪器。不同于验证失败会终止智能体运行的 LangSmith/Langfuse，Monocle 配置错误
    # 只会记录日志，网关仍会在未启用追踪的状态下继续服务。
    try:
        setup_monocle_tracing_if_enabled()
    except Exception:  # 可观测性绝不能阻断启动。
        logger.exception("Monocle tracing setup failed; continuing without it")

    # 预热 tiktoken 编码缓存，防止首次记忆注入请求阻塞在 BPE 数据下载上；受限网络可能
    # 无法访问相应 OpenAI/Azure 地址（见问题 #3402）。通过管理器的 ``warm`` 能力预热，
    # 使用 getattr 探测，非 DeerMem 后端会跳过。DeerMem.warm 会再次检查
    # token_counting 是否为 ``char`` 并提前返回，因此字符计数后端不会触及 tiktoken，
    # 也避免受限网络部署中额外的五秒探测（见问题 #3429）。
    try:
        from deerflow.agents.memory import get_memory_manager

        manager = get_memory_manager()
        warm = getattr(manager, "warm", None)
        if not callable(warm):
            logger.info("Memory backend %s has no warm-up hook; skipping tiktoken warm-up", type(manager).__name__)
        else:
            warmed = await asyncio.wait_for(
                asyncio.to_thread(warm),
                timeout=5,
            )
            if warmed:
                logger.info("tiktoken encoding cache warmed successfully")
            else:
                logger.warning("tiktoken encoding cache warm-up failed; token counting will use character-based fallback until tiktoken loads successfully")
    except TimeoutError:
        logger.warning("tiktoken encoding cache warm-up timed out; token counting will use character-based fallback until tiktoken loads successfully")
    except Exception:
        logger.warning("tiktoken warm-up skipped", exc_info=True)

    try:
        removed_upload_staging_files = await asyncio.to_thread(cleanup_stale_upload_staging_files)
        if removed_upload_staging_files:
            logger.info("Removed %d stale upload staging file(s)", removed_upload_staging_files)
    except Exception:
        logger.warning("Upload staging file cleanup skipped", exc_info=True)

    # 初始化 LangGraph 运行时组件（StreamBridge、RunManager、检查点与存储）。
    async with langgraph_runtime(app, startup_config):
        logger.info("LangGraph runtime initialised")

        # 检查管理员引导状态，并在管理员存在后迁移无主线程；必须在 langgraph_runtime
        # 之后执行，以使线程迁移可使用 app.state.store。
        await _ensure_admin_user(app)

        # 配置了即时通信频道时启动频道服务。
        try:
            from app.channels.service import start_channel_service

            channel_service = await start_channel_service(startup_config)
            logger.info("Channel service started: %s", channel_service.get_status())
        except Exception:
            logger.exception("No IM channels configured or channel service failed to start")

        try:
            from app.gateway.services import launch_scheduled_thread_run
            from app.scheduler import ScheduledTaskService

            if getattr(app.state, "scheduled_task_repo", None) is not None and getattr(app.state, "scheduled_task_run_repo", None) is not None:
                scheduled_task_service = ScheduledTaskService(
                    task_repo=app.state.scheduled_task_repo,
                    task_run_repo=app.state.scheduled_task_run_repo,
                    launch_run=lambda **kwargs: launch_scheduled_thread_run(app=app, **kwargs),
                    poll_interval_seconds=startup_config.scheduler.poll_interval_seconds,
                    lease_seconds=startup_config.scheduler.lease_seconds,
                    max_concurrent_runs=startup_config.scheduler.max_concurrent_runs,
                )
                app.state.scheduled_task_service = scheduled_task_service
                if startup_config.scheduler.enabled:
                    await scheduled_task_service.start()
        except Exception:
            logger.exception("Failed to initialize scheduled task service")

        yield

        try:
            await auth.close_oidc_service()
        except Exception:
            logger.exception("Failed to close OIDC service")

        # 关闭时停止频道服务，并设定时限以防工作进程卡死。
        try:
            from app.channels.service import stop_channel_service

            await asyncio.wait_for(
                stop_channel_service(),
                timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Channel service shutdown exceeded %.1fs; proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to stop channel service")

        if getattr(app.state, "scheduled_task_service", None) is not None:
            try:
                await app.state.scheduled_task_service.stop()
            except Exception:
                logger.exception("Failed to stop scheduled task service")

        # 在工作进程退出前排空记忆后端的待更新缓冲区（尽力而为且有时限）。上方已停止
        # 即时通信频道和调度器，因此排空期间不会有新的此类更新；LangGraph 运行时与在途
        # HTTP 请求仍可能在短暂窗口内完成记忆入队，但在排空复制缓冲区后新增的项目只会
        # 重置防抖计时器，仍保持当前的尽力而为语义。
        # 不设置主机级待处理或处理中守卫：``shutdown_flush`` 面对真正空闲的缓冲区会立即
        # 返回 ``True``，无条件调用成本很低，并将运行中工作进程的竞争完全留在持有缓冲区
        # 的后端内部；这样主机不会像只判断 ``pending_count > 0`` 的守卫那样遗忘该情况。
        # K8s 注意事项：网关 Helm 部署中 ``shutdown_flush_timeout_seconds`` 必须能纳入
        # Pod 的 ``terminationGracePeriodSeconds``（频道停止、此次排空与缓冲时间），否则
        # K8s 会在排空中途 SIGKILL，导致本次修复的数据丢失问题悄然重现。
        try:
            app_cfg = get_app_config()
            if app_cfg.memory.enabled:
                from deerflow.agents.memory import get_memory_manager

                manager = get_memory_manager()
                flush_timeout = app_cfg.memory.shutdown_flush_timeout_seconds
                completed = await asyncio.to_thread(manager.shutdown_flush, flush_timeout)
                if completed:
                    logger.info("Memory queue flush completed within %.1fs", flush_timeout)
                else:
                    logger.warning(
                        "Memory queue flush did not finish within %.1fs; remaining updates may be lost",
                        flush_timeout,
                    )
        except Exception:
            logger.exception("Failed to flush memory queue on shutdown")

    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    '''创建并配置 FastAPI 应用实例。

    返回已完成中间件、路由和生命周期装配的 FastAPI 应用。
    '''
    config = get_gateway_config()
    docs_url = "/docs" if config.enable_docs else None
    redoc_url = "/redoc" if config.enable_docs else None
    openapi_url = "/openapi.json" if config.enable_docs else None

    app = FastAPI(
        title="DeerFlow API Gateway",
        description="""

API Gateway for DeerFlow - A LangGraph-based AI agent backend with sandbox execution capabilities.


- **Models Management**: Query and retrieve available AI models
- **MCP Configuration**: Manage Model Context Protocol (MCP) server configurations
- **Memory Management**: Access and manage global memory data for personalized conversations
- **Skills Management**: Query and manage skills and their enabled status
- **Artifacts**: Access thread artifacts and generated files
- **Health Monitoring**: System health check endpoints


LangGraph-compatible requests are routed through nginx to this gateway.
This gateway provides runtime endpoints for agent runs plus custom endpoints for models, MCP configuration, skills, and artifacts.
        """,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        openapi_tags=[
            {
                "name": "models",
                "description": "Operations for querying available AI models and their configurations",
            },
            {
                "name": "mcp",
                "description": "Manage Model Context Protocol (MCP) server configurations",
            },
            {
                "name": "memory",
                "description": "Access and manage global memory data for personalized conversations",
            },
            {
                "name": "skills",
                "description": "Manage skills and their configurations",
            },
            {
                "name": "artifacts",
                "description": "Access and download thread artifacts and generated files",
            },
            {
                "name": "uploads",
                "description": "Upload and manage user files for threads",
            },
            {
                "name": "threads",
                "description": "Manage DeerFlow thread-local filesystem data",
            },
            {
                "name": "agents",
                "description": "Create and manage custom agents with per-agent config and prompts",
            },
            {
                "name": "suggestions",
                "description": "Generate follow-up question suggestions for conversations",
            },
            {
                "name": "input-polish",
                "description": "Polish composer draft input before sending",
            },
            {
                "name": "channels",
                "description": "Manage IM channel integrations (Feishu, Slack, Telegram)",
            },
            {
                "name": "assistants-compat",
                "description": "LangGraph Platform-compatible assistants API (stub)",
            },
            {
                "name": "runs",
                "description": "LangGraph Platform-compatible runs lifecycle (create, stream, cancel)",
            },
            {
                "name": "health",
                "description": "Health check and system status endpoints",
            },
        ],
    )

    # 认证：拒绝访问非公开路径的未认证请求，作为失败关闭的安全兜底。
    app.add_middleware(AuthMiddleware)

    # CSRF：为状态变更请求启用双重提交 Cookie 模式。
    app.add_middleware(CSRFMiddleware)

    # CORS：统一 nginx 入口默认同源。跨源浏览器客户端必须通过该网关显式白名单加入，
    # 使 CORS 与 CSRF 来源检查共享同一事实来源。
    cors_origins = sorted(get_configured_cors_origins())
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 请求追踪关联：logging.enhance.enabled=true 时，为每个 Gateway HTTP 请求绑定一个
    # 追踪 ID 并写入响应起始头。``logging`` 被登记为需重启字段，因此从启动期 AppConfig
    # 取得开关快照而非实时读取；否则运行时切换会令生命周期启动时仅安装一次的日志格式器
    # 与中间件失去同步。
    app.add_middleware(TraceMiddleware, enabled=_resolve_trace_enabled_for_app_construction())

    # 装配路由；模型 API 挂载至 /api/models。
    app.include_router(models.router)

    # 功能 API 挂载至 /api/features。
    app.include_router(features.router)

    # 控制台 API（跨线程可观测性）挂载至 /api/console。
    app.include_router(console.router)

    # MCP API 挂载至 /api/mcp。
    app.include_router(mcp.router)

    # 记忆 API 挂载至 /api/memory。
    app.include_router(memory.router)

    # 技能 API 挂载至 /api/skills。
    app.include_router(skills.router)

    # 工件 API 挂载至 /api/threads/{thread_id}/artifacts。
    app.include_router(artifacts.router)

    # 上传 API 挂载至 /api/threads/{thread_id}/uploads。
    app.include_router(uploads.router)

    # 线程清理 API 挂载至 /api/threads/{thread_id}。
    app.include_router(threads.router)

    # 定时任务 API 挂载至 /api/scheduled-tasks。
    app.include_router(scheduled_tasks.router)

    # 智能体 API 挂载至 /api/agents。
    app.include_router(agents.router)

    # 建议 API 挂载至 /api/threads/{thread_id}/suggestions。
    app.include_router(suggestions.router)

    # 输入润色 API 挂载至 /api/input-polish。
    app.include_router(input_polish.router)

    # 面向用户的即时通信频道连接 API 挂载至 /api/channels。
    app.include_router(channel_connections.router)

    # 频道 API 挂载至 /api/channels。
    app.include_router(channels.router)

    # 助手兼容 API（LangGraph Platform 存根）。
    app.include_router(assistants_compat.router)

    # 认证 API 挂载至 /api/v1/auth。
    app.include_router(auth.router)

    # 反馈 API 挂载至 /api/threads/{thread_id}/runs/{run_id}/feedback。
    app.include_router(feedback.router)

    # 线程运行 API（兼容 LangGraph Platform 的运行生命周期）。
    app.include_router(thread_runs.router)

    # 无状态运行 API（无需预先存在的线程即可流式执行或等待）。
    app.include_router(runs.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        '''返回服务健康状态。'''
        return {"status": "healthy", "service": "deer-flow-gateway"}

    return app


def _resolve_trace_enabled_for_app_construction() -> bool:
    '''解析追踪中间件开关，且不要求模块导入时存在 config.yaml。'''
    try:
        return resolve_trace_enabled(get_app_config())
    except FileNotFoundError:
        # 启动生命周期仍会在开始服务前严格加载配置。
        logger.debug("config.yaml not found while constructing Gateway app; TraceMiddleware disabled for this app instance")
        return False


# 为 uvicorn 创建应用实例。
app = create_app()
