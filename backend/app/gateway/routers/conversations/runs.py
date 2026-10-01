'''提供无需预先创建线程的运行、SSE 等待及按运行查询接口。'''

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer, get_feedback_repo, get_run_event_store, get_run_manager, get_run_store, get_stream_bridge
from app.gateway.pagination import trim_run_message_page
from app.gateway.routers.conversations.thread_runs import RunCreateRequest
from app.gateway.services import sse_consumer, start_run, wait_for_run_completion
from deerflow.runtime import serialize_channel_values_for_api

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])


def _resolve_thread_id(body: RunCreateRequest) -> str:
    '''复用运行配置中的线程 ID；未提供时生成新的临时线程标识。'''
    thread_id = (body.config or {}).get("configurable", {}).get("thread_id")
    if thread_id:
        return str(thread_id)
    return str(uuid.uuid4())


@router.post("/stream")
async def stateless_stream(body: RunCreateRequest, request: Request) -> StreamingResponse:
    '''启动无状态入口运行并通过 SSE 返回事件，可复用请求给出的线程历史。'''
    thread_id = _resolve_thread_id(body)
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    record = await start_run(body, thread_id, request)

    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/api/threads/{thread_id}/runs/{record.run_id}",
        },
    )


@router.post("/wait", response_model=dict)
async def stateless_wait(body: RunCreateRequest, request: Request) -> dict:
    '''启动无状态入口运行并等待结束，随后返回最终检查点状态或运行错误。'''
    thread_id = _resolve_thread_id(body)
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    record = await start_run(body, thread_id, request)

    completed = True
    if record.task is not None:
        completed = await wait_for_run_completion(bridge, record, request, run_mgr)

    if completed:
        checkpointer = get_checkpointer(request)
        config = {"configurable": {"thread_id": thread_id}}
        try:
            checkpoint_tuple = await checkpointer.aget_tuple(config)
            if checkpoint_tuple is not None:
                checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
                channel_values = checkpoint.get("channel_values", {})
                return serialize_channel_values_for_api(channel_values)
        except Exception:
            logger.exception("Failed to fetch final state for run %s", record.run_id)

    return {"status": record.status.value, "error": record.error}




async def _resolve_run(run_id: str, request: Request) -> dict:
    '''按当前用户读取运行记录；记录不存在或不可见时返回 404。'''
    run_store = get_run_store(request)
    record = await run_store.get(run_id)  # AUTO 根据当前用户上下文执行所有权过滤。
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return record


@router.get("/{run_id}/messages")
@require_permission("runs", "read")
async def run_messages(
    run_id: str,
    request: Request,
    limit: int = Query(default=50, le=200, ge=1),
    before_seq: int | None = Query(default=None),
    after_seq: int | None = Query(default=None),
) -> dict:
    '''按序号游标分页读取运行消息，并返回是否还有更多结果。'''
    run = await _resolve_run(run_id, request)
    event_store = get_run_event_store(request)
    rows = await event_store.list_messages_by_run(
        run["thread_id"],
        run_id,
        limit=limit + 1,
        before_seq=before_seq,
        after_seq=after_seq,
    )
    data, has_more = trim_run_message_page(rows, limit=limit, after_seq=after_seq)
    return {"data": data, "has_more": has_more}


@router.get("/{run_id}/feedback")
@require_permission("runs", "read")
async def run_feedback(run_id: str, request: Request) -> list[dict]:
    '''读取指定运行关联的全部用户反馈记录。'''
    run = await _resolve_run(run_id, request)
    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.list_by_run(run["thread_id"], run_id)
