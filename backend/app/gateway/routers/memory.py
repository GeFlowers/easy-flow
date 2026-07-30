'定义 memory 模块提供的职责与可复用接口。\n\nMemory API router for retrieving and managing global memory data.'

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
    "执行 _resolve_memory_user_id 的明确职责，并返回与调用约定一致的结果。\n\nResolve the memory owner for this request.\n\n    Honors the trusted internal owner header that channel workers attach when\n    acting for a connection owner, so an IM ``/memory`` command reads the bound\n    owner's memory instead of the synthetic internal user. The header is only\n    honored after ``AuthMiddleware`` validated the internal token (see\n    ``get_trusted_internal_owner_user_id``). Browser/API callers are never\n    internal, so this falls back to the normal contextvar-based effective user.\n\n    The trusted owner header carries the *raw* owner id, so sanitize it through\n    ``make_safe_user_id`` (the same normalization the channel file pipeline applies\n    via ``_safe_user_id_for_run``/``prepare_user_dir_for_raw_id``). This keeps the\n    memory bucket aligned with the owner's file/upload bucket and avoids a 500 when\n    the raw id contains characters ``_validate_user_id`` would reject.\n    "
    raw_owner = get_trusted_internal_owner_user_id(request)
    if raw_owner:
        return make_safe_user_id(raw_owner)
    return get_effective_user_id()


class ContextSection(BaseModel):
    '封装 ContextSection 的状态、协作关系与公开操作。\n\nModel for context sections (user and history).'

    summary: str = Field(default="", description="Summary content")
    updatedAt: str = Field(default="", description="Last update timestamp")


class UserContext(BaseModel):
    '封装 UserContext 的状态、协作关系与公开操作。\n\nModel for user context.'

    workContext: ContextSection = Field(default_factory=ContextSection)
    personalContext: ContextSection = Field(default_factory=ContextSection)
    topOfMind: ContextSection = Field(default_factory=ContextSection)


class HistoryContext(BaseModel):
    '封装 HistoryContext 的状态、协作关系与公开操作。\n\nModel for history context.'

    recentMonths: ContextSection = Field(default_factory=ContextSection)
    earlierContext: ContextSection = Field(default_factory=ContextSection)
    longTermBackground: ContextSection = Field(default_factory=ContextSection)


class Fact(BaseModel):
    '封装 Fact 的状态、协作关系与公开操作。\n\nModel for a memory fact.'

    id: str = Field(..., description="Unique identifier for the fact")
    content: str = Field(..., description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, description="Confidence score (0-1)")
    createdAt: str = Field(default="", description="Creation timestamp")
    source: str = Field(default="unknown", description="Source thread ID")
    sourceError: str | None = Field(default=None, description="Optional description of the prior mistake or wrong approach")


class MemoryResponse(BaseModel):
    '封装 MemoryResponse 的状态、协作关系与公开操作。\n\nResponse model for memory data.'

    version: str = Field(default="1.0", description="Memory schema version")
    lastUpdated: str = Field(default="", description="Last update timestamp")
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)


def _map_memory_fact_value_error(exc: ValueError) -> HTTPException:
    '执行 _map_memory_fact_value_error 的明确职责，并返回与调用约定一致的结果。\n\nConvert updater validation errors into stable API responses.'
    if exc.args and exc.args[0] == "confidence":
        detail = "Invalid confidence value; must be between 0 and 1."
    else:
        detail = "Memory fact content cannot be empty."
    return HTTPException(status_code=400, detail=detail)


def _require_capability(name: str, *, label: str):
    '执行 _require_capability 的明确职责，并返回与调用约定一致的结果。\n\nReturn a DeerMem-internal capability (bound method) or raise 501.\n\n    ``reload_memory`` / ``create_fact`` / ``delete_fact`` / ``update_fact`` are\n    not on the ``MemoryManager`` ABC -- they are DeerMem-internal. Probe with\n    ``hasattr`` rather than importing DeerMem, so this router has no hard\n    dependency on the default backend: a non-DeerMem (or removed) backend\n    simply lacks the attribute and the endpoint returns 501.\n    '
    manager = get_memory_manager()
    if not hasattr(manager, name):
        raise HTTPException(
            status_code=501,
            detail=f"Operation '{label}' not supported by memory backend '{type(manager).__name__}'.",
        )
    return getattr(manager, name)


class FactCreateRequest(BaseModel):
    '封装 FactCreateRequest 的状态、协作关系与公开操作。\n\nRequest model for creating a memory fact.'

    content: str = Field(..., min_length=1, description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence score (0-1)")


class FactPatchRequest(BaseModel):
    '封装 FactPatchRequest 的状态、协作关系与公开操作。\n\nPATCH request model that preserves existing values for omitted fields.'

    content: str | None = Field(default=None, min_length=1, description="Fact content")
    category: str | None = Field(default=None, description="Fact category")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score (0-1)")


class MemoryConfigResponse(BaseModel):
    '封装 MemoryConfigResponse 的状态、协作关系与公开操作。\n\nResponse model for memory configuration.'

    enabled: bool = Field(..., description="Whether the memory mechanism is enabled (call-site gate).")
    mode: Literal["middleware", "tool"] = Field(..., description="Memory operation mode: 'middleware' (passive per-turn LLM summarization) or 'tool' (model calls memory tools directly). Mechanism-level, applies to any backend.")
    injection_enabled: bool = Field(..., description="Whether memory is injected into the system prompt (call-site gate).")
    shutdown_flush_timeout_seconds: float = Field(..., description="Hard budget (s) to drain pending memory updates on Gateway graceful shutdown; must fit inside the pod's K8s terminationGracePeriodSeconds.")
    manager_class: str = Field(..., description="Active memory backend selector (backend name or dotted path).")
    backend_config: dict = Field(..., description="Backend-private config (self-interpreted by the backend).")


class MemoryStatusResponse(BaseModel):
    '封装 MemoryStatusResponse 的状态、协作关系与公开操作。\n\nResponse model for memory status.'

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
    '读取并返回，并遵守 get_memory 所表达的接口约束。\n\nGet the current global memory data.\n\n    Returns:\n        The current memory data with user context, history, and facts.\n\n    Example Response:\n        ```json\n        {\n            "version": "1.0",\n            "lastUpdated": "2024-01-15T10:30:00Z",\n            "user": {\n                "workContext": {"summary": "Working on DeerFlow project", "updatedAt": "..."},\n                "personalContext": {"summary": "Prefers concise responses", "updatedAt": "..."},\n                "topOfMind": {"summary": "Building memory API", "updatedAt": "..."}\n            },\n            "history": {\n                "recentMonths": {"summary": "Recent development activities", "updatedAt": "..."},\n                "earlierContext": {"summary": "", "updatedAt": ""},\n                "longTermBackground": {"summary": "", "updatedAt": ""}\n            },\n            "facts": [\n                {\n                    "id": "fact_abc123",\n                    "content": "User prefers TypeScript over JavaScript",\n                    "category": "preference",\n                    "confidence": 0.9,\n                    "createdAt": "2024-01-15T10:30:00Z",\n                    "source": "thread_xyz"\n                }\n            ]\n        }\n        ```\n    '
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
    '执行 reload_memory 的明确职责，并返回与调用约定一致的结果。\n\nReload memory data from file.\n\n    This forces a reload of the memory data from the storage file,\n    useful when the file has been modified externally.\n\n    Returns:\n        The reloaded memory data.\n    '
    user_id = _resolve_memory_user_id(http_request)
    manager = get_memory_manager()
    if hasattr(manager, "reload_memory"):
        memory_data = manager.reload_memory(user_id=user_id)
    else:
        # Non-DeerMem backends have no reload concept; return current memory.
        # (Asymmetry vs fact CRUD, which raises 501 when unsupported: reload is a
        # read-only refresh, so degrading to get_memory is safe and still useful;
        # silently no-op'ing a write would hide data loss, so writes fail loud.)
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
    '执行 clear_memory 的明确职责，并返回与调用约定一致的结果。\n\nClear all persisted memory data.'
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
    '创建并返回，并遵守 create_memory_fact_endpoint 所表达的接口约束。\n\nCreate a single fact manually.'
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
        # max_facts cap evicted the new (lower-confidence) fact; it was not stored.
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
    '删除目标资源并返回操作结果，并遵守 delete_memory_fact_endpoint 所表达的接口约束。\n\nDelete a single fact from memory by fact id.'
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
    '更新目标状态并返回最新结果，并遵守 update_memory_fact_endpoint 所表达的接口约束。\n\nPartially update a single fact manually.'
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
    '执行 export_memory 的明确职责，并返回与调用约定一致的结果。\n\nExport the current memory data.'
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
    '执行 import_memory 的明确职责，并返回与调用约定一致的结果。\n\nImport and persist memory data.'
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
    '读取并返回，并遵守 get_memory_config_endpoint 所表达的接口约束。\n\nGet the memory system configuration.\n\n    Returns:\n        The current memory configuration. The response is backend-agnostic:\n        ``enabled`` / ``injection_enabled`` / ``mode`` are mechanism-level\n        fields that apply to any backend (``mode`` selects middleware vs tool\n        operation), and ``backend_config`` is an opaque dict the active\n        backend (``manager_class``) self-interprets. DeerMem\'s knobs\n        (``storage_path``, ``max_facts``, ``debounce_seconds``, ...) live under\n        ``backend_config`` -- they are NOT top-level, because a non-DeerMem\n        backend has its own (different) knobs.\n\n    Example Response:\n        ```json\n        {\n            "enabled": true,\n            "injection_enabled": true,\n            "shutdown_flush_timeout_seconds": 30.0,\n            "mode": "middleware",\n            "manager_class": "deermem",\n            "backend_config": {\n                "storage_path": "/.../.deer-flow",\n                "debounce_seconds": 30,\n                "max_facts": 100,\n                "fact_confidence_threshold": 0.7,\n                "max_injection_tokens": 2000,\n                "token_counting": "tiktoken"\n            }\n        }\n        ```\n    '
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
    '读取并返回，并遵守 get_memory_status 所表达的接口约束。\n\nGet the memory system status including configuration and data.\n\n    Returns:\n        Combined memory configuration and current data.\n    '
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
