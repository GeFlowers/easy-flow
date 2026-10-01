'''提供用户长期记忆的读取、编辑、导入导出和状态查询接口。'''

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from deerflow.agents.memory import get_memory_manager
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import make_safe_user_id
from deerflow.runtime.user_context import get_effective_user_id

router = APIRouter(prefix="/api", tags=["memory"])


def _resolve_memory_user_id(request: Request) -> str:
    '''解析当前请求的记忆所有者；可信内部通道请求使用其绑定用户并规范化 ID。'''
    raw_owner = get_trusted_internal_owner_user_id(request)
    if raw_owner:
        return make_safe_user_id(raw_owner)
    return get_effective_user_id()


class ContextSection(BaseModel):
    '''表示带更新时间的单段记忆摘要。'''

    summary: str = Field(default="", description="Summary content")
    updatedAt: str = Field(default="", description="Last update timestamp")


class UserContext(BaseModel):
    '''表示工作、个人和当前关注事项等用户背景记忆。'''

    workContext: ContextSection = Field(default_factory=ContextSection)
    personalContext: ContextSection = Field(default_factory=ContextSection)
    topOfMind: ContextSection = Field(default_factory=ContextSection)


class HistoryContext(BaseModel):
    '''表示近期历史、较早上下文和长期背景摘要。'''

    recentMonths: ContextSection = Field(default_factory=ContextSection)
    earlierContext: ContextSection = Field(default_factory=ContextSection)
    longTermBackground: ContextSection = Field(default_factory=ContextSection)


class Fact(BaseModel):
    '''表示一条可分类、带置信度和来源信息的记忆事实。'''

    id: str = Field(..., description="Unique identifier for the fact")
    content: str = Field(..., description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, description="Confidence score (0-1)")
    createdAt: str = Field(default="", description="Creation timestamp")
    source: str = Field(default="unknown", description="Source thread ID")
    sourceError: str | None = Field(default=None, description="Optional description of the prior mistake or wrong approach")


class MemoryResponse(BaseModel):
    '''封装记忆版本、更新时间、用户背景、历史摘要及事实列表。'''

    version: str = Field(default="1.0", description="Memory schema version")
    lastUpdated: str = Field(default="", description="Last update timestamp")
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)


def _map_memory_fact_value_error(exc: ValueError) -> HTTPException:
    '''将事实校验异常映射为稳定的 HTTP 400 错误说明。'''
    if exc.args and exc.args[0] == "confidence":
        detail = "Invalid confidence value; must be between 0 and 1."
    else:
        detail = "Memory fact content cannot be empty."
    return HTTPException(status_code=400, detail=detail)


def _require_capability(name: str, *, label: str):
    '''从当前记忆后端获取可选操作能力；后端未实现时返回 HTTP 501。'''
    manager = get_memory_manager()
    if not hasattr(manager, name):
        raise HTTPException(
            status_code=501,
            detail=f"Operation '{label}' not supported by memory backend '{type(manager).__name__}'.",
        )
    return getattr(manager, name)


class FactCreateRequest(BaseModel):
    '''定义新增长期记忆事实所需的正文、类别和置信度。'''

    content: str = Field(..., min_length=1, description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence score (0-1)")


class FactPatchRequest(BaseModel):
    '''定义记忆事实的局部更新字段；未提供的字段保持原值。'''

    content: str | None = Field(default=None, min_length=1, description="Fact content")
    category: str | None = Field(default=None, description="Fact category")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score (0-1)")


class MemoryConfigResponse(BaseModel):
    '''描述记忆功能开关、运行模式和当前后端专属配置。'''

    enabled: bool = Field(..., description="Whether the memory mechanism is enabled (call-site gate).")
    mode: Literal["middleware", "tool"] = Field(..., description="Memory operation mode: 'middleware' (passive per-turn LLM summarization) or 'tool' (model calls memory tools directly). Mechanism-level, applies to any backend.")
    injection_enabled: bool = Field(..., description="Whether memory is injected into the system prompt (call-site gate).")
    shutdown_flush_timeout_seconds: float = Field(..., description="Hard budget (s) to drain pending memory updates on Gateway graceful shutdown; must fit inside the pod's K8s terminationGracePeriodSeconds.")
    manager_class: str = Field(..., description="Active memory backend selector (backend name or dotted path).")
    backend_config: dict = Field(..., description="Backend-private config (self-interpreted by the backend).")


class MemoryStatusResponse(BaseModel):
    '''组合记忆配置和当前记忆数据，供状态接口一次性返回。'''

    config: MemoryConfigResponse
    data: MemoryResponse


@router.get(
    "/memory",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Get Memory Data",
    description="Retrieve the current global memory data including user context, history, and facts.",
)
async def get_memory(http_request: Request) -> MemoryResponse:
    '''读取当前用户可访问的长期记忆数据。

        Returns:
            The current memory data with user context, history, and facts.

        Example Response:
            ```json
            {
                "version": "1.0",
                "lastUpdated": "2024-01-15T10:30:00Z",
                "user": {
                    "workContext": {"summary": "Working on DeerFlow project", "updatedAt": "..."},
                    "personalContext": {"summary": "Prefers concise responses", "updatedAt": "..."},
                    "topOfMind": {"summary": "Building memory API", "updatedAt": "..."}
                },
                "history": {
                    "recentMonths": {"summary": "Recent development activities", "updatedAt": "..."},
                    "earlierContext": {"summary": "", "updatedAt": ""},
                    "longTermBackground": {"summary": "", "updatedAt": ""}
                },
                "facts": [
                    {
                        "id": "fact_abc123",
                        "content": "User prefers TypeScript over JavaScript",
                        "category": "preference",
                        "confidence": 0.9,
                        "createdAt": "2024-01-15T10:30:00Z",
                        "source": "thread_xyz"
                    }
                ]
            }
            ```
    '''
    memory_data = get_memory_manager().get_memory(user_id=_resolve_memory_user_id(http_request))
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/reload",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Reload Memory Data",
    description="Reload memory data from the storage file, refreshing the in-memory cache.",
)
async def reload_memory(http_request: Request) -> MemoryResponse:
    '''要求后端刷新持久化记忆；不支持显式重载的后端退回读取当前数据。'''
    user_id = _resolve_memory_user_id(http_request)
    manager = get_memory_manager()
    if hasattr(manager, "reload_memory"):
        memory_data = manager.reload_memory(user_id=user_id)
    else:
        # 不支持重载的后端仍可安全返回当前数据；写操作则必须明确失败，避免掩盖数据未写入。
        memory_data = manager.get_memory(user_id=user_id)
    return MemoryResponse(**memory_data)


@router.delete(
    "/memory",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Clear All Memory Data",
    description="Delete all saved memory data and reset the memory structure to an empty state.",
)
async def clear_memory(http_request: Request) -> MemoryResponse:
    '''清除当前用户的持久化记忆并返回清空后的数据结构。'''
    try:
        memory_data = get_memory_manager().clear_memory(user_id=_resolve_memory_user_id(http_request))
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to clear memory data.") from exc

    return MemoryResponse(**memory_data)


@router.post(
    "/memory/facts",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Create Memory Fact",
    description="Create a single saved memory fact manually.",
)
async def create_memory_fact_endpoint(request: FactCreateRequest, http_request: Request) -> MemoryResponse:
    '''将用户手动提交的单条事实写入长期记忆。'''
    try:
        create_fact = _require_capability("create_fact", label="create fact")
        memory_data, fact_id = create_fact(
            content=request.content,
            category=request.category,
            confidence=request.confidence,
            user_id=_resolve_memory_user_id(http_request),
        )
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to create memory fact.") from exc

    if fact_id is None:
        # 新事实置信度较低，被 max_facts 上限淘汰，因此未写入记忆。
        raise HTTPException(status_code=409, detail="Fact was not stored because memory.max_facts kept higher-confidence facts")
    return MemoryResponse(**memory_data)


@router.delete(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Delete Memory Fact",
    description="Delete a single saved memory fact by its fact id.",
)
async def delete_memory_fact_endpoint(fact_id: str, http_request: Request) -> MemoryResponse:
    '''按事实 ID 删除长期记忆中的单条记录。'''
    try:
        delete_fact = _require_capability("delete_fact", label="delete fact")
        memory_data = delete_fact(fact_id, user_id=_resolve_memory_user_id(http_request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to delete memory fact.") from exc

    return MemoryResponse(**memory_data)


@router.patch(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Patch Memory Fact",
    description="Partially update a single saved memory fact by its fact id while preserving omitted fields.",
)
async def update_memory_fact_endpoint(fact_id: str, request: FactPatchRequest, http_request: Request) -> MemoryResponse:
    '''仅更新请求中提供字段的单条记忆事实。'''
    try:
        update_fact = _require_capability("update_fact", label="update fact")
        memory_data = update_fact(
            fact_id=fact_id,
            content=request.content,
            category=request.category,
            confidence=request.confidence,
            user_id=_resolve_memory_user_id(http_request),
        )
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to update memory fact.") from exc

    return MemoryResponse(**memory_data)


@router.get(
    "/memory/export",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Export Memory Data",
    description="Export the current global memory data as JSON for backup or transfer.",
)
async def export_memory(http_request: Request) -> MemoryResponse:
    '''读取并返回当前用户的记忆数据，供备份或迁移使用。'''
    memory_data = get_memory_manager().get_memory(user_id=_resolve_memory_user_id(http_request))
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/import",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Import Memory Data",
    description="Import and overwrite the current global memory data from a JSON payload.",
)
async def import_memory(request: MemoryResponse, http_request: Request) -> MemoryResponse:
    '''用请求中的完整数据覆盖当前用户记忆，并返回持久化后的结果。'''
    try:
        memory_data = get_memory_manager().import_memory(request.model_dump(), user_id=_resolve_memory_user_id(http_request))
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to import memory data.") from exc

    return MemoryResponse(**memory_data)


@router.get(
    "/memory/config",
    response_model=MemoryConfigResponse,
    summary="Get Memory Configuration",
    description="Retrieve the current memory system configuration.",
)
async def get_memory_config_endpoint() -> MemoryConfigResponse:
    '''读取当前生效的记忆系统配置。

        Returns:
            The current memory configuration. The response is backend-agnostic:
            ``enabled`` / ``injection_enabled`` / ``mode`` are mechanism-level
            fields that apply to any backend (``mode`` selects middleware vs tool
            operation), and ``backend_config`` is an opaque dict the active
            backend (``manager_class``) self-interprets. DeerMem's knobs
            (``storage_path``, ``max_facts``, ``debounce_seconds``, ...) live under
            ``backend_config`` -- they are NOT top-level, because a non-DeerMem
            backend has its own (different) knobs.

        Example Response:
            ```json
            {
                "enabled": true,
                "injection_enabled": true,
                "shutdown_flush_timeout_seconds": 30.0,
                "mode": "middleware",
                "manager_class": "deermem",
                "backend_config": {
                    "storage_path": "/.../.deer-flow",
                    "debounce_seconds": 30,
                    "max_facts": 100,
                    "fact_confidence_threshold": 0.7,
                    "max_injection_tokens": 2000,
                    "token_counting": "tiktoken"
                }
            }
            ```
    '''
    config = get_memory_config()
    return MemoryConfigResponse(
        enabled=config.enabled,
        mode=config.mode,
        injection_enabled=config.injection_enabled,
        shutdown_flush_timeout_seconds=config.shutdown_flush_timeout_seconds,
        manager_class=config.manager_class,
        backend_config=config.backend_config,
    )


@router.get(
    "/memory/status",
    response_model=MemoryStatusResponse,
    response_model_exclude_none=True,
    summary="Get Memory Status",
    description="Retrieve both memory configuration and current data in a single request.",
)
async def get_memory_status(http_request: Request) -> MemoryStatusResponse:
    '''读取记忆系统的运行状态、配置摘要和数据概况。

        Returns:
            Combined memory configuration and current data.
    '''
    config = get_memory_config()
    memory_data = get_memory_manager().get_memory(user_id=_resolve_memory_user_id(http_request))

    return MemoryStatusResponse(
        config=MemoryConfigResponse(
            enabled=config.enabled,
            mode=config.mode,
            injection_enabled=config.injection_enabled,
            shutdown_flush_timeout_seconds=config.shutdown_flush_timeout_seconds,
            manager_class=config.manager_class,
            backend_config=config.backend_config,
        ),
        data=MemoryResponse(**memory_data),
    )
