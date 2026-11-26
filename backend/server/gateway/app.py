'''组装 DeerFlow 网关的 HTTP 入口、运行时依赖和受控应用生命周期。'''

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.gateway.auth_disabled import warn_if_auth_disabled_enabled
from server.gateway.auth_middleware import AuthMiddleware
from server.gateway.config import get_gateway_config
from server.gateway.csrf_middleware import CSRFMiddleware, get_configured_cors_origins
from server.gateway.deps import langgraph_runtime
from server.gateway.routers import (
    artifacts,
    assistants_compat,
    auth,
    channel_connections,
    channels,
    console,
    feedback,
    global_instructions,
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
from server.gateway.trace_middleware import TraceMiddleware, resolve_trace_enabled
from deerflow.config import app_config as deerflow_app_config
from deerflow.logging_config import DEFAULT_LOG_DATE_FORMAT, DEFAULT_LOG_FORMAT, configure_logging
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    '''管理应用启动、运行期依赖装配及受控关闭的生命周期。'''

    # 启动时加载配置并检查必要的环境变量。
    # ``startup_config`` 只是用于一次性引导工作的本地快照（日志级别、
    # langgraph_runtime 引擎和频道）。请求期配置始终通过
    # ``server/gateway/deps.py::get_config()`` 中的 ``get_app_config()`` 解析，
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

        # 配置了即时通信频道时启动频道服务。
        try:
            from server.channels.service import start_channel_service

            channel_service = await start_channel_service(startup_config)
            logger.info("Channel service started: %s", channel_service.get_status())
        except Exception:
            logger.exception("No IM channels configured or channel service failed to start")

        try:
            from server.gateway.services import launch_scheduled_thread_run
            from server.scheduler import ScheduledTaskService

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

        if getattr(app.state, "wechat_login_flow", None) is not None:
            await app.state.wechat_login_flow.close()

        # 关闭时停止频道服务，并设定时限以防工作进程卡死。
        try:
            from server.channels.service import stop_channel_service

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

    # 控制台 API（跨线程可观测性）挂载至 /api/console。
    app.include_router(console.router)

    # MCP API 挂载至 /api/mcp。
    app.include_router(mcp.router)

    # 记忆 API 挂载至 /api/memory。
    app.include_router(memory.router)
    app.include_router(global_instructions.router)

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
