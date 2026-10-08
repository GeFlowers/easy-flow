'''提供线程元数据、检查点状态、分支、目标和上下文压缩等 HTTP 接口。'''

from __future__ import annotations

import copy
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from langgraph.checkpoint.base import empty_checkpoint, uuid6
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer, get_run_manager
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.utils import sanitize_log_param
from deerflow.config.paths import Paths, get_paths
from deerflow.config.summarization_config import ContextSize
from deerflow.runtime import serialize_channel_values_for_api
from deerflow.runtime.context_compaction import (
    ContextCompactionDisabled,
    ContextCompactionFailed,
    ThreadCompactionResult,
    compact_thread_context,
)
from deerflow.runtime.goal import (
    DEFAULT_MAX_GOAL_CONTINUATIONS,
    build_goal_state,
    ensure_thread_checkpoint,
    goal_thread_lock,
    read_thread_goal,
    write_thread_goal,
)
from deerflow.runtime.runs.worker import valid_duration_entry
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.file_io import run_file_io
from deerflow.utils.time import coerce_iso, now_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["threads"])


# 这些元数据字段由服务端控制，客户端不得设置。下方各个入站模型通过
# Pydantic ``@field_validator("metadata")`` 移除这些字段，避免恶意客户端伪造所有者身份并经接口回传。
# 这是纵深防御：数据库行仍以认证上下文中的用户编号写入 ``threads_meta.user_id``；此处用于封堵
# 元数据内容回显造成的缺口。
_SERVER_RESERVED_METADATA_KEYS: frozenset[str] = frozenset({"owner_id", "user_id"})
_SIDECAR_METADATA_KEY = "deerflow_sidecar"
_BRANCH_METADATA_KEY = "deerflow_branch"
_BRANCH_HISTORY_SCAN_LIMIT = 200


def _strip_reserved_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    '''复制线程元数据并移除只能由服务端写入的保留字段。'''
    if not metadata:
        return metadata or {}
    return {k: v for k, v in metadata.items() if k not in _SERVER_RESERVED_METADATA_KEYS}


def _message_id(message: Any) -> str | None:
    '''读取消息对象或字典中的标识。'''
    if isinstance(message, dict):
        raw = message.get("id")
    else:
        raw = getattr(message, "id", None)
    return raw if isinstance(raw, str) and raw else None


def _message_type(message: Any) -> str | None:
    '''读取消息对象或字典中的类型。'''
    if isinstance(message, dict):
        raw = message.get("type")
    else:
        raw = getattr(message, "type", None)
    return raw if isinstance(raw, str) and raw else None


def _message_additional_kwargs(message: Any) -> dict[str, Any]:
    '''读取消息附加元数据；缺失时返回空字典。'''
    if isinstance(message, dict):
        raw = message.get("additional_kwargs")
    else:
        raw = getattr(message, "additional_kwargs", None)
    return raw if isinstance(raw, dict) else {}


def _is_branch_visible_message(message: Any) -> bool:
    '''判断消息是否可在分支复制时展示。'''
    if _message_additional_kwargs(message).get("hide_from_ui") is True:
        return False
    return _message_type(message) in {"human", "ai"}


def _is_branch_assistant_message(message: Any) -> bool:
    '''判断消息是否为助手消息。'''
    return _message_type(message) == "ai"


def _checkpoint_messages(checkpoint_tuple: Any) -> list[Any]:
    '''从检查点元组提取消息通道值。'''
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) or {}
    messages = channel_values.get("messages") or []
    return list(messages) if isinstance(messages, list) else []


def _checkpoint_id(checkpoint_tuple: Any) -> str | None:
    '''从检查点配置提取检查点标识。'''
    config = getattr(checkpoint_tuple, "config", {}) or {}
    raw = config.get("configurable", {}).get("checkpoint_id")
    return raw if isinstance(raw, str) and raw else None


def _matches_branch_target(messages: list[Any], target_message_ids: set[str]) -> bool:
    '''判断检查点消息是否包含分支目标消息。'''
    if not target_message_ids:
        return False

    index_by_id = {_message_id(message): index for index, message in enumerate(messages) if _message_id(message)}
    if not target_message_ids.issubset(index_by_id.keys()):
        return False
    if any(not _is_branch_assistant_message(messages[index_by_id[message_id]]) for message_id in target_message_ids):
        return False

    target_end_index = max(index_by_id[message_id] for message_id in target_message_ids)
    return not any(_is_branch_visible_message(message) for message in messages[target_end_index + 1 :])


async def _find_branch_checkpoint(checkpointer: Any, thread_id: str, target_message_ids: set[str]) -> Any:
    '''遍历线程检查点，定位包含目标消息的分支基点。'''
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=_BRANCH_HISTORY_SCAN_LIMIT):
            if _matches_branch_target(_checkpoint_messages(checkpoint_tuple), target_message_ids):
                return checkpoint_tuple
    except Exception:
        logger.exception("Failed to scan branch checkpoint history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to find branch checkpoint")
    raise HTTPException(status_code=409, detail="This turn can no longer be branched from.")


async def _branch_targets_latest_turn(checkpointer: Any, thread_id: str, target_message_ids: set[str]) -> bool:
    '''判断目标是否为最新可见轮次；检查失败时按历史轮次处理以避免复制较新的工作区。'''
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=_BRANCH_HISTORY_SCAN_LIMIT):
            messages = _checkpoint_messages(checkpoint_tuple)
            if not messages:
                continue
            return _matches_branch_target(messages, target_message_ids)
    except Exception:
        logger.warning(
            "Failed to resolve latest turn for thread %s; treating branch as historical",
            sanitize_log_param(thread_id),
            exc_info=True,
        )
    return False


def _ignore_branch_user_data(directory: str, names: list[str]) -> set[str]:
    '''筛除复制分支用户数据时不应继承的临时或运行文件。'''
    ignored: set[str] = set()
    base = Path(directory)
    for name in names:
        path = base / name
        if name.startswith(".upload-") and name.endswith(".part"):
            ignored.add(name)
        elif path.is_symlink():
            ignored.add(name)
    return ignored


def _copy_branch_user_data_sync(paths: Paths, source_thread_id: str, target_thread_id: str, *, user_id: str) -> str:
    '''在工作线程中复制同一用户的分支沙箱数据目录。'''
    source = paths.sandbox_user_data_dir(source_thread_id, user_id=user_id)
    target = paths.sandbox_user_data_dir(target_thread_id, user_id=user_id)
    if not source.exists():
        return "not_found"

    shutil.copytree(source, target, ignore=_ignore_branch_user_data, dirs_exist_ok=True)
    return "current_thread_best_effort"


async def _copy_branch_user_data(source_thread_id: str, target_thread_id: str) -> str:
    '''异步调度当前用户的分支数据复制操作。'''
    paths = get_paths()
    user_id = get_effective_user_id()
    try:
        return await run_file_io(_copy_branch_user_data_sync, paths, source_thread_id, target_thread_id, user_id=user_id)
    except Exception:
        logger.warning(
            "Failed to copy user-data for branch %s -> %s",
            sanitize_log_param(source_thread_id),
            sanitize_log_param(target_thread_id),
            exc_info=True,
        )
        return "failed"


def _default_branch_display_name(source_title: Any, *, source_is_branch: bool = False) -> str | None:
    '''复用源线程的非空标题；已有分支同样保持原名，空标题交给后续生成流程。'''
    if not isinstance(source_title, str):
        return None

    return source_title.strip() or None




class ThreadDeleteResponse(BaseModel):
    '''返回线程清理是否成功及对应说明。'''

    success: bool
    message: str


class ThreadResponse(BaseModel):
    '''线程列表和详情接口使用的线程状态响应。'''

    thread_id: str = Field(description="Unique thread identifier")
    status: str = Field(default="idle", description="Thread status: idle, busy, interrupted, error")
    created_at: str = Field(default="", description="ISO timestamp")
    updated_at: str = Field(default="", description="ISO timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Thread metadata")
    values: dict[str, Any] = Field(default_factory=dict, description="Current state channel values")
    interrupts: dict[str, Any] = Field(default_factory=dict, description="Pending interrupts")


class ThreadCreateRequest(BaseModel):
    '''定义新线程的可选标识、Agent 归属和初始元数据。'''

    thread_id: str | None = Field(default=None, description="Optional thread ID (auto-generated if omitted)")
    assistant_id: str | None = Field(default=None, description="Associate thread with an assistant")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Initial metadata")

    _strip_reserved = field_validator("metadata")(classmethod(lambda cls, v: _strip_reserved_metadata(v)))


class ThreadSearchRequest(BaseModel):
    '''定义线程元数据精确筛选、状态过滤和分页参数。'''

    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata filter (exact match)")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    status: str | None = Field(default=None, description="Filter by thread status")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_filters(cls, v: dict[str, Any]) -> dict[str, Any]:
        '''校验元数据筛选键和值为持久化查询支持的安全类型。'''
        if not v:
            return v
        from deerflow.persistence.json_compat import validate_metadata_filter_key, validate_metadata_filter_value

        bad_entries: list[str] = []
        for key, value in v.items():
            if not validate_metadata_filter_key(key):
                bad_entries.append(f"{key!r} (unsafe key)")
            elif not validate_metadata_filter_value(value):
                bad_entries.append(f"{key!r} (unsupported value type {type(value).__name__})")
        if bad_entries:
            raise ValueError(f"Invalid metadata filter entries: {', '.join(bad_entries)}")
        return v


class ThreadStateResponse(BaseModel):
    '''返回线程检查点中的状态值、待执行节点和中断任务信息。'''

    values: dict[str, Any] = Field(default_factory=dict, description="Current channel values")
    next: list[str] = Field(default_factory=list, description="Next tasks to execute")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Checkpoint metadata")
    checkpoint: dict[str, Any] = Field(default_factory=dict, description="Checkpoint info")
    checkpoint_id: str | None = Field(default=None, description="Current checkpoint ID")
    parent_checkpoint_id: str | None = Field(default=None, description="Parent checkpoint ID")
    created_at: str | None = Field(default=None, description="Checkpoint timestamp")
    tasks: list[dict[str, Any]] = Field(default_factory=list, description="Interrupted task details")


class ThreadPatchRequest(BaseModel):
    '''定义合并到线程现有元数据中的字段。'''

    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata to merge")

    _strip_reserved = field_validator("metadata")(classmethod(lambda cls, v: _strip_reserved_metadata(v)))


class ThreadStateUpdateRequest(BaseModel):
    '''定义人工介入后更新线程状态或从指定检查点恢复所需的数据。'''

    values: dict[str, Any] | None = Field(default=None, description="Channel values to merge")
    checkpoint_id: str | None = Field(default=None, description="Checkpoint to branch from")
    checkpoint: dict[str, Any] | None = Field(default=None, description="Full checkpoint object")
    as_node: str | None = Field(default=None, description="Node identity for the update")


class ThreadGoalRequest(BaseModel):
    '''定义线程目标文本和允许的自动续跑次数。'''

    objective: str = Field(..., min_length=1, max_length=4000, description="Completion condition for the agent to keep pursuing")
    max_continuations: int = Field(
        default=DEFAULT_MAX_GOAL_CONTINUATIONS,
        ge=0,
        le=DEFAULT_MAX_GOAL_CONTINUATIONS,
        description="Maximum automatic hidden continuation turns before stopping",
    )


class ThreadGoalResponse(BaseModel):
    '''返回当前线程目标；未设置目标时为 null。'''

    goal: dict[str, Any] | None = Field(default=None, description="Current goal state, or null when no goal is active")


class ThreadCompactRequest(BaseModel):
    '''定义手动压缩上下文时的强制执行、保留策略和 Agent 归属参数。'''

    force: bool = Field(default=True, description="Run compaction even if automatic summarization thresholds are not met")
    keep: ContextSize | None = Field(default=None, description="Optional retention policy for this compaction only")
    agent_name: str | None = Field(default=None, max_length=128, description="Optional custom agent name for memory attribution")


class ThreadCompactResponse(BaseModel):
    '''报告上下文压缩结果、消息保留数量、摘要状态和新检查点。'''

    thread_id: str
    compacted: bool
    reason: str | None = None
    removed_message_count: int = 0
    preserved_message_count: int = 0
    summary_updated: bool = False
    checkpoint_id: str | None = None
    total_tokens: int = 0


class HistoryEntry(BaseModel):
    '''表示单个检查点的父子关系、状态内容和调度信息。'''

    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    next: list[str] = Field(default_factory=list)


class ThreadHistoryRequest(BaseModel):
    '''定义检查点历史分页数量和游标。'''

    limit: int = Field(default=10, ge=1, le=100, description="Maximum entries")
    before: str | None = Field(default=None, description="Cursor for pagination")


class ThreadBranchRequest(BaseModel):
    '''指定分支来源的助手消息及新线程可选标题。'''

    message_id: str = Field(..., min_length=1, description="Target assistant message ID to branch from")
    message_ids: list[str] = Field(default_factory=list, description="All assistant message IDs in the target turn")
    title: str | None = Field(default=None, max_length=256, description="Optional title for the branched thread")


class ThreadBranchResponse(BaseModel):
    '''返回新线程标识、父线程、分支检查点及工作区复制结果。'''

    thread_id: str
    parent_thread_id: str
    parent_checkpoint_id: str
    branched_from_message_id: str
    workspace_clone_mode: str




def _delete_thread_data(thread_id: str, paths: Paths | None = None, *, user_id: str | None = None) -> ThreadDeleteResponse:
    '''删除线程在本地用户数据目录中的文件，并将缺失目录视为成功。'''
    path_manager = paths or get_paths()
    try:
        path_manager.delete_thread_dir(thread_id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError:
        # 线程数据目录可能尚未创建，因此本地文件缺失不影响整体删除流程。
        logger.debug("No local thread data to delete for %s", sanitize_log_param(thread_id))
        return ThreadDeleteResponse(success=True, message=f"No local data for {thread_id}")
    except Exception as exc:
        logger.exception("Failed to delete thread data for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to delete local thread data.") from exc

    logger.info("Deleted local thread data for %s", sanitize_log_param(thread_id))
    return ThreadDeleteResponse(success=True, message=f"Deleted local thread data for {thread_id}")


def _derive_thread_status(checkpoint_tuple) -> str:
    '''根据检查点待写入错误和待执行任务推导线程错误、中断或空闲状态。'''
    if checkpoint_tuple is None:
        return "idle"
    pending_writes = getattr(checkpoint_tuple, "pending_writes", None) or []

    # 待写入记录包含错误时，线程处于错误状态。
    for pw in pending_writes:
        if len(pw) >= 2 and pw[1] == "__error__":
            return "error"

    # 仍有待执行任务通常表示运行被中断。
    tasks = getattr(checkpoint_tuple, "tasks", None)
    if tasks:
        return "interrupted"

    return "idle"


async def _ensure_thread_for_goal(thread_id: str, request: Request) -> None:
    '''为目标操作补齐线程元数据和根检查点，支持尚未运行过的新线程。'''
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    checkpointer = get_checkpointer(request)
    thread_owner_user_id = get_trusted_internal_owner_user_id(request)
    thread_owner_kwargs = {"user_id": thread_owner_user_id} if thread_owner_user_id else {}

    record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if record is None and thread_owner_user_id:
        unscoped_record = await thread_store.get(thread_id, user_id=None)
        if unscoped_record is not None:
            if unscoped_record.get("user_id") != thread_owner_user_id:
                await thread_store.update_owner(thread_id, thread_owner_user_id, user_id=None)
            record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if record is None:
        try:
            await thread_store.create(thread_id, metadata={}, **thread_owner_kwargs)
        except Exception:
            logger.exception("Failed to create thread_meta for goal thread %s", sanitize_log_param(thread_id))
            raise HTTPException(status_code=500, detail="Failed to create thread") from None

    try:
        await ensure_thread_checkpoint(checkpointer, thread_id)
    except Exception:
        logger.exception("Failed to create goal checkpoint for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread checkpoint") from None




@router.delete("/{thread_id}", response_model=ThreadDeleteResponse)
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_thread_data(thread_id: str, request: Request) -> ThreadDeleteResponse:
    '''删除指定线程保存在本地文件系统中的用户数据。

        清理 DeerFlow 管理的线程文件、LangGraph 检查点和 PostgreSQL 线程元数据。
    '''
    from app.gateway.deps import get_thread_store

    # 清理线程所属用户目录下的本地文件。
    response = _delete_thread_data(thread_id, user_id=get_effective_user_id())

    # 尽力删除 LangGraph 检查点。
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None:
        try:
            if hasattr(checkpointer, "adelete_thread"):
                await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.debug("Could not delete checkpoints for thread %s (not critical)", sanitize_log_param(thread_id))

    # 同步删除线程元数据，避免已删除线程继续出现在搜索结果中。
    try:
        thread_store = get_thread_store(request)
        await thread_store.delete(thread_id)
    except Exception:
        logger.debug("Could not delete thread_meta for %s (not critical)", sanitize_log_param(thread_id))

    return response


async def _resolve_existing_thread(
    thread_store: Any,
    thread_id: str,
    thread_owner_user_id: str | None,
    thread_owner_kwargs: dict[str, Any],
) -> dict | None:
    '''读取幂等创建所指向的现有线程，并在可信内部调用时认领无主旧记录。'''
    existing_record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if existing_record is None and thread_owner_user_id:
        unscoped_record = await thread_store.get(thread_id, user_id=None)
        if unscoped_record is not None:
            if unscoped_record.get("user_id") != thread_owner_user_id:
                await thread_store.update_owner(thread_id, thread_owner_user_id, user_id=None)
            existing_record = await thread_store.get(thread_id, **thread_owner_kwargs)
    return existing_record


def _existing_thread_response(thread_id: str, record: dict) -> ThreadResponse:
    '''将已存在的线程记录转换为 API 响应。'''
    return ThreadResponse(
        thread_id=thread_id,
        status=record.get("status", "idle"),
        created_at=coerce_iso(record.get("created_at", "")),
        updated_at=coerce_iso(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
    )


@router.post("", response_model=ThreadResponse)
async def create_thread(body: ThreadCreateRequest, request: Request) -> ThreadResponse:
    '''创建线程并初始化其元数据与检查点。

        写入 thread_meta 记录（使线程出现在 /threads/search 中）和空检查点（使状态接口可立即使用）。
        操作具有幂等性：thread_id 已存在时返回已有记录。
    '''
    from app.gateway.deps import get_thread_store

    checkpointer = get_checkpointer(request)
    thread_store = get_thread_store(request)
    thread_id = body.thread_id or str(uuid.uuid4())
    now = now_iso()
    thread_owner_user_id = get_trusted_internal_owner_user_id(request)
    thread_owner_kwargs = {"user_id": thread_owner_user_id} if thread_owner_user_id else {}
    # ``body.metadata`` 已由 ``ThreadCreateRequest._strip_reserved`` 移除服务端保留字段，详见模型定义。

    # 幂等处理：记录已存在时直接返回。
    existing_record = await _resolve_existing_thread(thread_store, thread_id, thread_owner_user_id, thread_owner_kwargs)
    if existing_record is not None:
        return _existing_thread_response(thread_id, existing_record)

    # 写入 thread_meta，使会话立即出现在 /threads/search 结果中。
    try:
        await thread_store.create(
            thread_id,
            assistant_id=getattr(body, "assistant_id", None),
            **thread_owner_kwargs,
            metadata=body.metadata,
        )
    except IntegrityError:
        # 上方的幂等查询与此处插入不是原子操作：相同 thread_id 的并发请求可能先行提交，
        # 因此数据库存储会以主键重复拒绝本次插入。
        # 唯一键冲突说明并发请求已先写入同一线程；复用相同的归属校验结果满足幂等语义。
        existing_record = await _resolve_existing_thread(thread_store, thread_id, thread_owner_user_id, thread_owner_kwargs)
        if existing_record is not None:
            return _existing_thread_response(thread_id, existing_record)
        # 若发生主键重复却无法读取已有记录，则属于真实故障。
        logger.exception("Failed to write thread_meta for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")
    except Exception:
        # 非并发竞态导致的故障必须向调用方报告，不能静默当作成功响应。
        logger.exception("Failed to write thread_meta for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        ckpt_metadata = {
            "step": -1,
            "source": "input",
            "writes": None,
            "parents": {},
            **body.metadata,
            "created_at": now,
        }
        await checkpointer.aput(config, empty_checkpoint(), ckpt_metadata, {})
    except Exception:
        logger.exception("Failed to create checkpoint for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")

    logger.info("Thread created: %s", sanitize_log_param(thread_id))
    return ThreadResponse(
        thread_id=thread_id,
        status="idle",
        created_at=now,
        updated_at=now,
        metadata=body.metadata,
    )


@router.post("/{thread_id}/branches", response_model=ThreadBranchResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def branch_thread(thread_id: str, body: ThreadBranchRequest, request: Request) -> ThreadBranchResponse:
    '''从已完成的助手轮次创建新线程，并仅在目标为最新轮次时复制当前工作区。'''
    from app.gateway.deps import get_thread_store

    checkpointer = get_checkpointer(request)
    thread_store = get_thread_store(request)

    source_record = await thread_store.get(thread_id)
    if source_record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    source_metadata = source_record.get("metadata") or {}
    if source_metadata.get(_SIDECAR_METADATA_KEY) is True:
        raise HTTPException(status_code=409, detail="Branching is only available in the main conversation.")

    target_message_ids = {body.message_id, *body.message_ids}
    checkpoint_tuple = await _find_branch_checkpoint(checkpointer, thread_id, target_message_ids)
    parent_checkpoint_id = _checkpoint_id(checkpoint_tuple)
    if not parent_checkpoint_id:
        raise HTTPException(status_code=409, detail="This turn can no longer be branched from.")

    # 工作区文件不随检查点回滚；仅从最新轮次分支时复制，避免把之后生成的文件带入历史分支。
    branch_from_latest_turn = await _branch_targets_latest_turn(checkpointer, thread_id, target_message_ids)

    new_thread_id = str(uuid.uuid4())
    now = now_iso()
    branch_metadata = {
        _BRANCH_METADATA_KEY: True,
        "branch_parent_thread_id": thread_id,
        "branch_parent_checkpoint_id": parent_checkpoint_id,
        "branch_parent_message_id": body.message_id,
        "branch_created_at": now,
    }

    display_name = body.title or _default_branch_display_name(
        source_record.get("display_name"),
        source_is_branch=source_metadata.get(_BRANCH_METADATA_KEY) is True,
    )
    thread_owner_user_id = get_trusted_internal_owner_user_id(request)
    thread_owner_kwargs = {"user_id": thread_owner_user_id} if thread_owner_user_id else {}

    checkpoint = copy.deepcopy(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata = copy.deepcopy(getattr(checkpoint_tuple, "metadata", {}) or {})
    checkpoint["id"] = str(uuid6())
    metadata.update(
        {
            "source": "branch",
            "updated_at": now,
            "created_at": now,
            **branch_metadata,
        }
    )

    write_config = {"configurable": {"thread_id": new_thread_id, "checkpoint_ns": ""}}
    new_versions = dict(checkpoint.get("channel_versions", {}) or {})
    try:
        await checkpointer.aput(write_config, checkpoint, metadata, new_versions)
    except Exception:
        logger.exception("Failed to write branch checkpoint for thread %s", sanitize_log_param(new_thread_id))
        raise HTTPException(status_code=500, detail="Failed to create branch") from None

    try:
        await thread_store.create(
            new_thread_id,
            assistant_id=source_record.get("assistant_id"),
            display_name=display_name,
            metadata=branch_metadata,
            **thread_owner_kwargs,
        )
    except Exception:
        logger.exception("Failed to write branch thread_meta for %s", sanitize_log_param(new_thread_id))
        raise HTTPException(status_code=500, detail="Failed to create branch") from None

    if branch_from_latest_turn:
        workspace_clone_mode = await _copy_branch_user_data(thread_id, new_thread_id)
    else:
        workspace_clone_mode = "skipped_historical_turn"
    return ThreadBranchResponse(
        thread_id=new_thread_id,
        parent_thread_id=thread_id,
        parent_checkpoint_id=parent_checkpoint_id,
        branched_from_message_id=body.message_id,
        workspace_clone_mode=workspace_clone_mode,
    )


@router.post("/search", response_model=list[ThreadResponse])
async def search_threads(body: ThreadSearchRequest, request: Request) -> list[ThreadResponse]:
    '''按筛选条件分页查询当前用户的线程，并转换为 API 响应。'''
    from app.gateway.deps import get_thread_store
    from deerflow.persistence.thread_meta import InvalidMetadataFilterError

    repo = get_thread_store(request)
    try:
        rows = await repo.search(
            metadata=body.metadata or None,
            status=body.status,
            limit=body.limit,
            offset=body.offset,
        )
    except InvalidMetadataFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        ThreadResponse(
            thread_id=r["thread_id"],
            status=r.get("status", "idle"),
            # 将旧版本写入的 Unix 秒时间转换为 ISO 格式；SQL 行中的 ISO 字符串会原样保留。
            created_at=coerce_iso(r.get("created_at", "")),
            updated_at=coerce_iso(r.get("updated_at", "")),
            metadata=r.get("metadata", {}),
            values={"title": r["display_name"]} if r.get("display_name") else {},
            interrupts={},
        )
        for r in rows
    ]


@router.patch("/{thread_id}", response_model=ThreadResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def patch_thread(thread_id: str, body: ThreadPatchRequest, request: Request) -> ThreadResponse:
    '''将请求元数据合并到线程记录，并返回更新后的线程响应。'''
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    record = await thread_store.get(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # ThreadPatchRequest 已在校验阶段移除服务端保留字段。
    try:
        await thread_store.update_metadata(thread_id, body.metadata)
    except Exception:
        logger.exception("Failed to patch thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread")

    # 重新读取合并后的元数据和更新时间。
    record = await thread_store.get(thread_id) or record
    return ThreadResponse(
        thread_id=thread_id,
        status=record.get("status", "idle"),
        created_at=coerce_iso(record.get("created_at", "")),
        updated_at=coerce_iso(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
    )


@router.get("/{thread_id}", response_model=ThreadResponse)
@require_permission("threads", "read", owner_check=True)
async def get_thread(thread_id: str, request: Request) -> ThreadResponse:
    '''读取线程元数据及当前用户可见的状态信息。

        从 ThreadMetaStore 读取元数据，并根据检查点保存器推导准确的运行状态。
        对引入 ThreadMetaStore 之前创建的旧线程，回退为仅查询检查点保存器。
    '''
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    checkpointer = get_checkpointer(request)

    record: dict | None = await thread_store.get(thread_id)

    # 优先依据检查点推导当前运行状态。
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get checkpoint for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread")

    if record is None and checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # 兼容只有检查点、尚无线程元数据表记录的旧线程。
    if record is None and checkpoint_tuple is not None:
        ckpt_meta = getattr(checkpoint_tuple, "metadata", {}) or {}
        record = {
            "thread_id": thread_id,
            "status": "idle",
            "created_at": coerce_iso(ckpt_meta.get("created_at", "")),
            "updated_at": coerce_iso(ckpt_meta.get("updated_at", ckpt_meta.get("created_at", ""))),
            "metadata": {k: v for k, v in ckpt_meta.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents")},
        }

    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    status = _derive_thread_status(checkpoint_tuple) if checkpoint_tuple is not None else record.get("status", "idle")
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {} if checkpoint_tuple is not None else {}
    channel_values = checkpoint.get("channel_values", {})

    return ThreadResponse(
        thread_id=thread_id,
        status=status,
        created_at=coerce_iso(record.get("created_at", "")),
        updated_at=coerce_iso(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
        values=serialize_channel_values_for_api(channel_values),
    )


@router.get("/{thread_id}/goal", response_model=ThreadGoalResponse)
@require_permission("threads", "read", owner_check=True)
async def get_thread_goal(thread_id: str, request: Request) -> ThreadGoalResponse:
    '''返回线程当前活动目标；尚未设置时返回空值。'''
    checkpointer = get_checkpointer(request)
    try:
        goal = await read_thread_goal(checkpointer, thread_id)
    except Exception:
        logger.exception("Failed to read goal for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to read thread goal") from None
    return ThreadGoalResponse(goal=goal)


@router.put("/{thread_id}/goal", response_model=ThreadGoalResponse)
@require_permission("threads", "write", owner_check=True)
async def set_thread_goal(thread_id: str, body: ThreadGoalRequest, request: Request) -> ThreadGoalResponse:
    '''创建或替换线程活动目标；若线程尚无检查点则在写入前补建。'''
    checkpointer = get_checkpointer(request)
    await _ensure_thread_for_goal(thread_id, request)
    try:
        goal = build_goal_state(body.objective, max_continuations=body.max_continuations)
        async with goal_thread_lock(thread_id):
            await write_thread_goal(checkpointer, thread_id, goal, as_node="goal", create_if_missing=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("Failed to set goal for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to set thread goal") from None
    return ThreadGoalResponse(goal=goal)


@router.delete("/{thread_id}/goal", response_model=ThreadGoalResponse)
@require_permission("threads", "write", owner_check=True)
async def clear_thread_goal(thread_id: str, request: Request) -> ThreadGoalResponse:
    '''清除线程活动目标；线程或检查点不存在时仍返回空目标。'''
    checkpointer = get_checkpointer(request)
    try:
        async with goal_thread_lock(thread_id):
            await write_thread_goal(checkpointer, thread_id, None, as_node="goal")
    except LookupError:
        return ThreadGoalResponse(goal=None)
    except Exception:
        logger.exception("Failed to clear goal for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to clear thread goal") from None
    return ThreadGoalResponse(goal=None)


def _thread_compact_response(result: ThreadCompactionResult) -> ThreadCompactResponse:
    '''将线程压缩服务结果转换为路由响应模型。'''
    return ThreadCompactResponse(
        thread_id=result.thread_id,
        compacted=result.compacted,
        reason=result.reason,
        removed_message_count=result.removed_message_count,
        preserved_message_count=result.preserved_message_count,
        summary_updated=result.summary_updated,
        checkpoint_id=result.checkpoint_id,
        total_tokens=result.total_tokens,
    )


@router.post("/{thread_id}/compact", response_model=ThreadCompactResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def compact_thread(thread_id: str, body: ThreadCompactRequest, request: Request) -> ThreadCompactResponse:
    '''在没有进行中运行时压缩线程上下文，并保留近期可见消息。'''
    run_manager = get_run_manager(request)
    checkpointer = get_checkpointer(request)
    keep = body.keep.to_tuple() if body.keep is not None else None
    try:
        async with goal_thread_lock(thread_id):
            if await run_manager.has_inflight(thread_id):
                raise HTTPException(status_code=409, detail="Thread has a run in flight. Compact after the run finishes.")
            result = await compact_thread_context(
                checkpointer,
                thread_id,
                keep=keep,
                force=body.force,
                user_id=get_effective_user_id(),
                agent_name=body.agent_name,
            )
    except ContextCompactionDisabled:
        raise HTTPException(status_code=409, detail="Context compaction is disabled.") from None
    except ContextCompactionFailed:
        raise HTTPException(status_code=500, detail="Failed to compact thread context.") from None
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to compact thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to compact thread context.") from None
    return _thread_compact_response(result)


@router.get("/{thread_id}/state", response_model=ThreadStateResponse)
@require_permission("threads", "read", owner_check=True)
async def get_thread_state(thread_id: str, request: Request) -> ThreadStateResponse:
    '''读取线程最新的 LangGraph 状态快照。

        序列化通道值，确保 LangChain 消息对象转换为可安全编码为 JSON 的字典。
    '''
    checkpointer = get_checkpointer(request)

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
    checkpoint_id = None
    ckpt_config = getattr(checkpoint_tuple, "config", {})
    if ckpt_config:
        checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id")

    channel_values = checkpoint.get("channel_values", {})

    parent_config = getattr(checkpoint_tuple, "parent_config", None)
    parent_checkpoint_id = None
    if parent_config:
        parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id")

    tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
    next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]
    tasks = [{"id": getattr(t, "id", ""), "name": getattr(t, "name", "")} for t in tasks_raw]

    values = serialize_channel_values_for_api(channel_values)

    return ThreadStateResponse(
        values=values,
        next=next_tasks,
        metadata=metadata,
        checkpoint={"id": checkpoint_id, "ts": coerce_iso(metadata.get("created_at", ""))},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=coerce_iso(metadata.get("created_at", "")),
        tasks=tasks,
    )


@router.post("/{thread_id}/state", response_model=ThreadStateResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def update_thread_state(thread_id: str, body: ThreadStateUpdateRequest, request: Request) -> ThreadStateResponse:
    '''把指定字段合并到最新检查点，并同步更新线程标题索引。'''
    from app.gateway.deps import get_thread_store

    checkpointer = get_checkpointer(request)
    thread_store = get_thread_store(request)

    # aput 要求配置中包含 checkpoint_ns；默认使用 ""（根图命名空间）。checkpoint_id 可选，
    # 省略时读取该线程最新的检查点。
    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    if body.checkpoint_id:
        read_config["configurable"]["checkpoint_id"] = body.checkpoint_id

    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception:
        logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # 在可变副本上操作，避免意外修改缓存对象。
    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))

    if body.values:
        channel_values.update(body.values)

    checkpoint["channel_values"] = channel_values
    metadata["updated_at"] = now_iso()

    if body.as_node:
        metadata["source"] = "update"
        metadata["step"] = metadata.get("step", 0) + 1
        metadata["writes"] = {body.as_node: body.values}

    # 分配新的检查点编号，使 aput 插入新记录而非原位替换现有记录。使用按时间排序的 uuid6，
    # 而不是随机 uuid4，确保新编号在字典顺序上大于旧编号；LangGraph 检查点保存器通过编号
    # 的字符串顺序确定最新检查点，这与 uuid6 的时间顺序一致。
    checkpoint["id"] = str(uuid6())

    # aput 要求配置中包含 checkpoint_ns，因此沿用读取时的配置（其中总有 checkpoint_ns=""）。
    # 新检查点编号已写入 checkpoint["id"]；不要在配置中传入旧 checkpoint_id，确保写入依据
    # 新检查点内容，而不是刚才读取的旧记录。
    # 保存器会沿用写入检查点的 ID，因此响应配置可返回本次新生成的 UUID。
    write_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    try:
        new_config = await checkpointer.aput(write_config, checkpoint, metadata, {})
    except Exception:
        logger.exception("Failed to update state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread state")

    new_checkpoint_id: str | None = None
    if isinstance(new_config, dict):
        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id")

    # 同步标题索引，使线程搜索立即显示新的标题。
    if thread_store and body.values and "title" in body.values:
        new_title = body.values["title"]
        if new_title:  # 跳过空字符串和 None。
            try:
                await thread_store.update_display_name(thread_id, new_title)
            except Exception:
                logger.debug("Failed to sync title to thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

    return ThreadStateResponse(
        values=serialize_channel_values_for_api(channel_values),
        next=[],
        metadata=metadata,
        checkpoint_id=new_checkpoint_id,
        created_at=coerce_iso(metadata.get("created_at", "")),
    )


def _ai_message_lacks_duration(message: dict[str, Any]) -> bool:
    '''判断助手消息是否尚未写入回合耗时。'''
    additional_kwargs = message.get("additional_kwargs")
    return message.get("type") == "ai" and (not isinstance(additional_kwargs, dict) or "turn_duration" not in additional_kwargs)


def _checkpoint_run_durations(metadata: Any) -> dict[str, int]:
    '''从检查点元数据提取运行耗时映射。'''
    raw_durations = metadata.get("run_durations") if isinstance(metadata, dict) else None
    if not isinstance(raw_durations, dict):
        return {}
    return {run_id: duration_seconds for run_id, duration_seconds in raw_durations.items() if valid_duration_entry(run_id, duration_seconds)}


def _set_message_turn_duration(message: dict[str, Any], run_id: str, run_durations: dict[str, int]) -> None:
    '''在匹配运行的助手消息附加回合耗时。'''
    if message.get("type") != "ai" or run_id not in run_durations:
        return
    additional_kwargs = message.get("additional_kwargs")
    if not isinstance(additional_kwargs, dict):
        additional_kwargs = {}
        message["additional_kwargs"] = additional_kwargs
    additional_kwargs.setdefault("turn_duration", run_durations[run_id])


@router.post("/{thread_id}/history", response_model=list[HistoryEntry])
@require_permission("threads", "read", owner_check=True)
async def get_thread_history(
    thread_id: str,
    body: ThreadHistoryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> list[HistoryEntry]:
    '''按检查点顺序分页读取线程的状态历史。

        消息从检查点保存器的通道值中读取（这是权威数据源），并通过
        :func:`~deerflow.runtime.serialization.serialize_channel_values` 序列化。
        仅最新的第一个检查点携带 ``messages`` 字段，避免每条历史记录重复包含消息。
    '''
    checkpointer = get_checkpointer(request)

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if body.before:
        config["configurable"]["checkpoint_id"] = body.before

    entries: list[HistoryEntry] = []
    is_latest_checkpoint = True
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=body.limit):
            ckpt_config = getattr(checkpoint_tuple, "config", {})
            parent_config = getattr(checkpoint_tuple, "parent_config", None)
            metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}

            checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id", "")
            parent_id = None
            if parent_config:
                parent_id = parent_config.get("configurable", {}).get("checkpoint_id")

            channel_values = checkpoint.get("channel_values", {})

            # 从检查点的 channel_values 构造状态值。
            values: dict[str, Any] = {}
            if title := channel_values.get("title"):
                values["title"] = title
            if thread_data := channel_values.get("thread_data"):
                values["thread_data"] = thread_data

            # 仅在最新的检查点记录中附加消息。
            if is_latest_checkpoint:
                messages = channel_values.get("messages")
                if messages:
                    serialized_msgs = serialize_channel_values_for_api({"messages": messages}).get("messages", [])
                    try:
                        # 人类消息标记轮次边界。新检查点会在元数据中保存已完成轮次的时长，
                        # 因此无需修改 messages 通道。
                        checkpoint_run_durations = _checkpoint_run_durations(metadata)
                        current_turn_run_id = None
                        for msg in serialized_msgs:
                            if msg.get("type") == "human":
                                additional_kwargs = msg.get("additional_kwargs")
                                if isinstance(additional_kwargs, dict):
                                    run_id = additional_kwargs.get("run_id")
                                    if isinstance(run_id, str) and run_id:
                                        current_turn_run_id = run_id
                                continue

                            if msg.get("type") not in {"ai", "tool"} or not current_turn_run_id:
                                continue

                            msg.setdefault("run_id", current_turn_run_id)
                            _set_message_turn_duration(msg, current_turn_run_id, checkpoint_run_durations)

                        # 对缺少时长元数据的旧检查点，通过事件存储和运行管理器关联一次运行时长，
                        # 再仅写入检查点元数据完成升级。
                        if any(_ai_message_lacks_duration(msg) for msg in serialized_msgs):
                            from app.gateway.deps import get_run_event_store, get_run_manager
                            from app.gateway.routers.conversations.thread_runs import compute_run_durations
                            from deerflow.runtime.runs.worker import persist_run_durations

                            run_mgr = get_run_manager(request)
                            event_store = get_run_event_store(request)

                            runs = await run_mgr.list_by_thread(thread_id)
                            events = await event_store.list_messages(thread_id, limit=1000)

                            if runs:
                                run_durations = compute_run_durations(runs)
                                msg_to_run = {}
                                for event in events:
                                    content = event.get("content", {})
                                    run_id = event.get("run_id")
                                    if isinstance(content, dict) and content.get("type") == "ai" and "id" in content and isinstance(run_id, str) and run_id:
                                        msg_to_run[content["id"]] = run_id

                                current_turn_run_id = None
                                for msg in serialized_msgs:
                                    if msg.get("type") == "human":
                                        additional_kwargs = msg.get("additional_kwargs")
                                        if isinstance(additional_kwargs, dict):
                                            run_id = additional_kwargs.get("run_id")
                                            if isinstance(run_id, str) and run_id:
                                                current_turn_run_id = run_id
                                        continue

                                    if msg.get("type") not in {"ai", "tool"}:
                                        continue
                                    run_id = msg_to_run.get(msg.get("id")) or current_turn_run_id
                                    if run_id:
                                        msg["run_id"] = run_id
                                        _set_message_turn_duration(msg, run_id, run_durations)

                                # 此处有意采用尽力而为的“读取时迁移”：在响应发出后保存旧版元数据，
                                # 避免历史请求等待活动流持有的同线程检查点锁。
                                background_tasks.add_task(
                                    persist_run_durations,
                                    checkpointer=checkpointer,
                                    thread_id=thread_id,
                                    durations=run_durations,
                                )

                    except Exception:
                        logger.warning("Failed to inject turn_duration for thread %s", thread_id, exc_info=True)

                    values["messages"] = serialized_msgs

            is_latest_checkpoint = False

            # 推导后续任务。
            tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
            next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]

            # 移除元数据中的 LangGraph 内部字段。
            user_meta = {k: v for k, v in metadata.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents", "run_durations")}
            # 保留 step 字段，以便了解执行顺序。
            if "step" in metadata:
                user_meta["step"] = metadata["step"]

            entries.append(
                HistoryEntry(
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_id,
                    metadata=user_meta,
                    values=values,
                    created_at=coerce_iso(metadata.get("created_at", "")),
                    next=next_tasks,
                )
            )
    except Exception:
        logger.exception("Failed to get history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread history")

    return entries
