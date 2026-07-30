"""提供子代理步骤和运行事件的构造功能。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from deerflow.utils.messages import message_content_to_text

from .status_contract import normalize_token_usage

#: Default per-step character cap for the ``text`` field. Tool outputs (web
#: search results, file contents) can be large; this cap bounds the persisted
#: run-event row and the streamed frame. It only affects display/storage — the
#: subagent's own LLM context is bounded separately by ToolOutputBudgetMiddleware.
SUBAGENT_STEP_MAX_CHARS = 8192

#: ``RunEvent.category`` for persisted subagent steps. A dedicated category (not
#: ``"message"``) keeps these events out of ``list_messages`` (the thread message
#: feed) while still being returned by ``list_events`` for fetch-on-expand (#3779).
SUBAGENT_EVENT_CATEGORY = "subagent"

#: Map of ``task_*`` terminal custom-event types to their persisted status.
_TERMINAL_EVENT_STATUS: dict[str, str] = {
    "task_completed": "completed",
    "task_failed": "failed",
    "task_cancelled": "cancelled",
    "task_timed_out": "timed_out",
}


def capture_step_message(
    message: BaseMessage,
    captured: list[dict[str, Any]],
    seen_ids: set[str],
) -> bool:
    """处理步骤事件提取与构造，并保持既有状态语义。"""
    if not isinstance(message, (AIMessage, ToolMessage)):
        return False

    message_dict = message.model_dump()
    message_id = message_dict.get("id")
    if message_id:
        if message_id in seen_ids:
            return False
    elif message_dict in captured:
        return False

    captured.append(message_dict)
    if message_id:
        seen_ids.add(message_id)
    return True


def capture_new_step_messages(
    messages: list[BaseMessage],
    captured: list[dict[str, Any]],
    seen_ids: set[str],
    processed_count: int,
) -> int:
    """处理步骤事件提取与构造，并保持既有状态语义。"""
    total = len(messages)
    if total < processed_count:
        processed_count = total
    if total > processed_count:
        for message in messages[processed_count:total]:
            capture_step_message(message, captured, seen_ids)
        return total
    if messages:
        capture_step_message(messages[-1], captured, seen_ids)
    return max(processed_count, total)


def truncate_step_text(text: str, max_chars: int) -> tuple[str, bool]:
    """处理步骤事件提取与构造，并保持既有状态语义。"""
    if max_chars >= 0 and len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _bounded_tool_call(call: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """处理步骤事件提取与构造，并保持既有状态语义。"""
    name = call.get("name")
    args = call.get("args")
    serialized = args if isinstance(args, str) else json.dumps(args, default=str, ensure_ascii=False)
    if max_chars >= 0 and len(serialized) > max_chars:
        return {"name": name, "args": serialized[:max_chars], "args_truncated": True}
    return {"name": name, "args": args}


def build_subagent_step(
    message: dict[str, Any],
    *,
    task_id: str,
    message_index: int,
    max_chars: int = SUBAGENT_STEP_MAX_CHARS,
) -> dict[str, Any]:
    """处理步骤事件提取与构造，并保持既有状态语义。"""
    kind = "tool" if message.get("type") == "tool" else "ai"
    # ``... or ""`` keeps a tool-call-only turn's content=None rendering as ""
    # (message_content_to_text would otherwise str()-ify it to "None").
    text, truncated = truncate_step_text(message_content_to_text(message.get("content") or ""), max_chars)

    step: dict[str, Any] = {
        "task_id": task_id,
        "message_index": message_index,
        "kind": kind,
        "text": text,
        "truncated": truncated,
    }

    if kind == "tool":
        step["tool_name"] = message.get("name")
    else:
        step["tool_calls"] = [_bounded_tool_call(call, max_chars) for call in (message.get("tool_calls") or [])]

    return step


def subagent_run_event(chunk: Any) -> dict[str, Any] | None:
    """处理步骤事件提取与构造，并保持既有状态语义。"""
    if not isinstance(chunk, dict):
        return None

    event = chunk.get("type")
    if not isinstance(event, str) or not event.startswith("task_"):
        return None

    task_id = chunk.get("task_id")

    if event == "task_started":
        return {
            "event_type": "subagent.start",
            "category": SUBAGENT_EVENT_CATEGORY,
            "content": {"task_id": task_id, "description": chunk.get("description")},
            "metadata": {"task_id": task_id},
        }

    if event == "task_running":
        message_index = chunk.get("message_index")
        return {
            "event_type": "subagent.step",
            "category": SUBAGENT_EVENT_CATEGORY,
            "content": build_subagent_step(chunk.get("message") or {}, task_id=task_id, message_index=message_index),
            "metadata": {"task_id": task_id, "message_index": message_index},
        }

    status = _TERMINAL_EVENT_STATUS.get(event)
    if status is not None:
        content: dict[str, Any] = {"task_id": task_id, "status": status}
        model_name = chunk.get("model_name")
        if isinstance(model_name, str) and model_name.strip():
            content["model_name"] = model_name.strip()
        usage = normalize_token_usage(chunk.get("usage"))
        if usage is not None:
            content["usage"] = usage
        # The final result/error can be a multi-page report; cap it so the
        # persisted run-event row stays bounded (it is also kept verbatim on the
        # terminal ToolMessage, which the card reads separately).
        if chunk.get("result") is not None:
            result, result_truncated = truncate_step_text(str(chunk["result"]), SUBAGENT_STEP_MAX_CHARS)
            content["result"] = result
            if result_truncated:
                content["result_truncated"] = True
        if chunk.get("error") is not None:
            error, error_truncated = truncate_step_text(str(chunk["error"]), SUBAGENT_STEP_MAX_CHARS)
            content["error"] = error
            if error_truncated:
                content["error_truncated"] = True
        return {
            "event_type": "subagent.end",
            "category": SUBAGENT_EVENT_CATEGORY,
            "content": content,
            "metadata": {"task_id": task_id},
        }

    return None
