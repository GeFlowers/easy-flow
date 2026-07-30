'定义 seed_runs_router 模块提供的职责与可复用接口。\n\nTest-only run/message seeder for the multi-run render-order e2e (issue #3352).\n\nMounted **only** by ``scripts/run_replay_gateway.py`` (the replay e2e gateway)\nand never by the production app, so it cannot ship. It lets a Playwright spec\nstand up a thread with >=2 runs whose per-run messages exercise the frontend\'s\nreload / history-rebuild ordering path — with no real model, no recording, and\nno API key.\n\nWhy a seeder instead of recording a conversation: issue #3352 only reproduces\nwhen the checkpoint no longer holds the older messages (post-compression), so\nthe frontend rebuilds them from the per-run history endpoints. A seeder lets us\ncreate exactly that precondition deterministically — runs in the run store +\nper-run ``category="message"`` events, and **no checkpoint** — so on reload the\nbuggy ``findLatestUnloadedRunIndex`` + prepend in ``core/threads/hooks.ts`` is\nthe sole source of truth and its reversed order becomes observable.\n\nIt writes through the gateway\'s OWN ``app.state.run_store`` +\n``app.state.run_event_store`` using the request\'s auth context, so the seeded\n``user_id`` matches the browser session that reads it back. The event shape\nmirrors exactly what ``runtime/journal.py`` writes for real runs\n(``event_type`` ``llm.human.input`` / ``llm.ai.response``, ``category``\n``"message"``, ``content`` = ``message.model_dump()``, ``metadata.caller`` =\n``"lead_agent"``).\n'

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/test-only", tags=["test-only"])

# Mirror runtime/journal.py: human prompts are recorded as ``llm.human.input``
# and assistant turns as ``llm.ai.response``; both land in ``category="message"``.
_EVENT_TYPE = {"human": "llm.human.input", "ai": "llm.ai.response"}


class SeedMessage(BaseModel):
    '封装 SeedMessage 的状态、协作关系与公开操作'
    role: Literal["human", "ai"]
    content: str
    id: str


class SeedRun(BaseModel):
    '封装 SeedRun 的状态、协作关系与公开操作'
    run_id: str
    # ISO timestamp; RunManager.list_by_thread sorts newest-first by created_at,
    # so a later created_at must mean a later run for the ordering to be faithful.
    created_at: str
    messages: list[SeedMessage]


class SeedRunsBody(BaseModel):
    '封装 SeedRunsBody 的状态、协作关系与公开操作'
    thread_id: str
    runs: list[SeedRun]


@router.post("/seed-runs")
async def seed_runs(body: SeedRunsBody, request: Request) -> dict:
    "执行 seed_runs 的明确职责，并返回与调用约定一致的结果。\n\nSeed runs + per-run message events for the authenticated user.\n\n    No checkpoint is written: that is the whole point — it forces the frontend's\n    reload path to rebuild history from the per-run endpoints (the #3352 bug\n    site) instead of the (correctly ordered) checkpoint snapshot.\n    "
    from langchain_core.messages import AIMessage, HumanMessage

    run_store = request.app.state.run_store
    event_store = request.app.state.run_event_store

    for run in body.runs:
        # user_id defaults (AUTO) to the request's auth context, matching the
        # browser session that will read these runs back via GET /runs.
        await run_store.put(
            run.run_id,
            thread_id=body.thread_id,
            assistant_id="lead_agent",
            status="success",
            created_at=run.created_at,
        )
        events = []
        for m in run.messages:
            msg = (HumanMessage if m.role == "human" else AIMessage)(content=m.content, id=m.id)
            events.append(
                {
                    "thread_id": body.thread_id,
                    "run_id": run.run_id,
                    "event_type": _EVENT_TYPE[m.role],
                    "category": "message",
                    "content": msg.model_dump(),
                    "metadata": {"caller": "lead_agent"},
                    "created_at": run.created_at,
                }
            )
        # One batch per run so seq is monotonic and run1's messages precede
        # run2's; the gateway reads them back per-run anyway.
        await event_store.put_batch(events)

    return {"ok": True, "thread_id": body.thread_id, "runs": len(body.runs)}
