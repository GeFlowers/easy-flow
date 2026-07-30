'定义 runs 模块提供的职责与可复用接口。\n\nStateless runs endpoints -- stream and wait without a pre-existing thread.\n\nThese endpoints auto-create a temporary thread when no ``thread_id`` is\nsupplied in the request body.  When a ``thread_id`` **is** provided, it\nis reused so that conversation history is preserved across calls.\n'

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer, get_feedback_repo, get_run_event_store, get_run_manager, get_run_store, get_stream_bridge
from app.gateway.pagination import trim_run_message_page
from app.gateway.routers.thread_runs import RunCreateRequest
from app.gateway.services import sse_consumer, start_run, wait_for_run_completion
from deerflow.runtime import serialize_channel_values_for_api

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])


def _resolve_thread_id(body: RunCreateRequest) -> str:
    '执行 _resolve_thread_id 的明确职责，并返回与调用约定一致的结果。\n\nReturn the thread_id from the request body, or generate a new one.'
    thread_id = (body.config or {}).get("configurable", {}).get("thread_id")
    if thread_id:
        return str(thread_id)
    return str(uuid.uuid4())


@router.post("/stream")
async def stateless_stream(body: RunCreateRequest, request: Request) -> StreamingResponse:
    '执行 stateless_stream 的明确职责，并返回与调用约定一致的结果。\n\nCreate a run and stream events via SSE.\n\n    If ``config.configurable.thread_id`` is provided, the run is created\n    on the given thread so that conversation history is preserved.\n    Otherwise a new temporary thread is created.\n    '
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
    '执行 stateless_wait 的明确职责，并返回与调用约定一致的结果。\n\nCreate a run and block until completion.\n\n    If ``config.configurable.thread_id`` is provided, the run is created\n    on the given thread so that conversation history is preserved.\n    Otherwise a new temporary thread is created.\n    '
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


# ---------------------------------------------------------------------------
# Run-scoped read endpoints
# ---------------------------------------------------------------------------


async def _resolve_run(run_id: str, request: Request) -> dict:
    '执行 _resolve_run 的明确职责，并返回与调用约定一致的结果。\n\nFetch run by run_id with user ownership check. Raises 404 if not found.'
    run_store = get_run_store(request)
    record = await run_store.get(run_id)  # user_id=AUTO filters by contextvar
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
    '执行任务并返回执行结果，并遵守 run_messages 所表达的接口约束。\n\nReturn paginated messages for a run (cursor-based).\n\n    Pagination:\n    - after_seq: messages with seq > after_seq (forward)\n    - before_seq: messages with seq < before_seq (backward)\n    - neither: latest messages\n\n    Response: { data: [...], has_more: bool }\n    '
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
    '执行任务并返回执行结果，并遵守 run_feedback 所表达的接口约束。\n\nReturn all feedback for a run.'
    run = await _resolve_run(run_id, request)
    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.list_by_run(run["thread_id"], run_id)
