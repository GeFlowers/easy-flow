'''从消息历史提取子代理委派结果，并将其压缩成受预算限制的模型上下文。'''

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from html import escape
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from deerflow.agents.thread_state import DelegationEntry
from deerflow.subagents.status_contract import (
    read_subagent_result_metadata,
)

_RESULT_BRIEF_CAP = 2000
_DESCRIPTION_CAP = 200
_LEDGER_RENDER_CHAR_BUDGET = 6000
_LEDGER_ENTRY_RESULT_RENDER_CAP = 120
_STATUS_ONLY_RESULT_BRIEFS = {
    "failed": "任务失败。",
    "cancelled": "任务已被用户取消。",
    "timed_out": "任务超时。",
    "polling_timed_out": "任务轮询超时。",
}


def _utc_now_iso() -> str:
    '''返回以 Z 结尾的当前 UTC ISO 8601 时间字符串。'''
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bound_text(text: str, cap: int = _RESULT_BRIEF_CAP) -> str:
    '''按固定比例保留文本首尾，确定性截断结果摘要而不调用模型。'''
    if len(text) <= cap:
        return text
    if cap <= 0:
        return ""
    head = cap * 2 // 3
    omitted_marker = "\n...\n"
    if cap <= len(omitted_marker):
        return text[:cap]
    tail = cap - head - len(omitted_marker)
    if tail <= 0:
        return text[:cap]
    return f"{text[:head]}{omitted_marker}{text[-tail:]}"


def _escape_context_text(value: object) -> str:
    '''压缩空白并转义将注入模型上下文的文本。'''
    return escape(" ".join(str(value).split()), quote=False)


def _status_guidance(status: str, stop_reason: str | None = None) -> str:
    '''根据委派状态和可选终止原因生成后续行动指引。'''
    if stop_reason:
        # 守卫预算可能提前结束运行；状态仍描述运行结果，stop_reason 单独说明触发的预算上限。
        if status == "completed":
            return "达到安全限制并返回部分结果；请复用部分结果、缩小范围后重试，或提高单个代理的预算（max_turns / token_budget）"
        return "达到安全限制且没有可用结果；请缩小范围后重试，或提高单个代理的预算（max_turns / token_budget）"
    if status == "in_progress":
        return "已委派；不要重复委派；请等待结果或基于结果继续工作"
    if status == "completed":
        return "结果已完成；不要重复委派；请复用此结果"
    if status == "failed":
        return "此前尝试失败；可以调整计划后重试"
    if status == "cancelled":
        return "此前尝试已取消；可以调整计划后重试"
    if status == "timed_out":
        return "此前尝试超时；可以调整计划后重试"
    if status == "polling_timed_out":
        return "polling 此前尝试超时；可以调整计划后重试"
    return "此前已有尝试；重试前请检查状态"


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    '''从标准或嵌套 function 格式的工具调用中提取名称。'''
    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return ""


def _tool_call_id(tool_call: dict[str, Any]) -> str | None:
    '''提取工具调用 ID，并在缺失时返回 None。'''
    tool_call_id = tool_call.get("id")
    return str(tool_call_id) if tool_call_id else None


def _tool_call_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    '''提取字典类型的工具调用参数，其他情况返回空字典。'''
    args = tool_call.get("args")
    return args if isinstance(args, dict) else {}


def extract_delegations(messages: list[AnyMessage]) -> list[DelegationEntry]:
    '''配对历史中的 task 工具调用及其结果消息，生成按调用顺序排列的委派记录。'''
    entries_by_id: dict[str, DelegationEntry] = {}
    order: list[str] = []
    now = _utc_now_iso()
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls or []:
            if _tool_call_name(tool_call) != "task":
                continue
            tool_call_id = _tool_call_id(tool_call)
            if tool_call_id is None:
                continue
            args = _tool_call_args(tool_call)
            description = str(args.get("description") or args.get("prompt") or "")[:_DESCRIPTION_CAP]
            if tool_call_id not in entries_by_id:
                order.append(tool_call_id)
            entries_by_id[tool_call_id] = {
                "id": tool_call_id,
                "description": description,
                "subagent_type": str(args.get("subagent_type") or ""),
                "status": "in_progress",
                "created_at": now,
            }

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = str(message.tool_call_id) if message.tool_call_id else ""
        entry = entries_by_id.get(tool_call_id)
        if entry is None:
            continue
        structured = read_subagent_result_metadata(message.additional_kwargs)
        if structured is None:
            continue
        entry["status"] = structured["status"]
        stop_reason = structured.get("stop_reason")
        if stop_reason:
            entry["stop_reason"] = stop_reason
        result_text = structured.get("result_brief") or structured.get("error") or _STATUS_ONLY_RESULT_BRIEFS.get(structured["status"])
        if result_text:
            result_sha256 = structured.get("result_sha256") or hashlib.sha256(result_text.encode("utf-8")).hexdigest()
            entry.update(
                {
                    "result_brief": _bound_text(result_text),
                    "result_sha256": result_sha256,
                    "result_ref": str(message.id or tool_call_id),
                }
            )
    return [entries_by_id[tool_call_id] for tool_call_id in order]


def _fits_budget(lines: list[str], candidate: str, max_chars: int) -> bool:
    '''判断追加候选行后是否仍满足总字符预算。'''
    return len("\n".join([*lines, candidate])) <= max_chars


def _render_entry_line(entry: DelegationEntry) -> str:
    '''将单条委派记录渲染为安全的模型可见列表行。'''
    status = _escape_context_text(entry["status"])
    description = _escape_context_text(entry["description"])
    subagent_type = _escape_context_text(entry["subagent_type"])
    guidance = _status_guidance(entry["status"], entry.get("stop_reason"))
    line = f"- [{status}] {description}（由 {subagent_type} 执行；{guidance}）"
    result_brief = entry.get("result_brief")
    if result_brief:
        line += f" -> {_escape_context_text(_bound_text(result_brief, _LEDGER_ENTRY_RESULT_RENDER_CAP))}"
    return line


def render_delegation_ledger(entries: list[DelegationEntry], *, max_chars: int = _LEDGER_RENDER_CHAR_BUDGET) -> str:
    '''将委派记录按新到旧顺序渲染为模型上下文，并在字符预算不足时省略旧记录。'''
    if not entries:
        return ""

    lines = [
        "## 已委派的工作",
        "最新条目排在前面。进行中的条目已完成委派。已完成的条目包含可复用结果。失败、取消或超时的条目代表此前的尝试。",
    ]
    omitted = 0
    for index, entry in enumerate(reversed(entries)):
        line = _render_entry_line(entry)
        if _fits_budget(lines, line, max_chars):
            lines.append(line)
            continue
        omitted = len(entries) - index
        break

    if omitted:
        omitted_line = f"- ... {omitted} 条较早的委派记录因上下文预算限制而从当前模型视图中省略"
        while len(lines) > 1 and not _fits_budget(lines, omitted_line, max_chars):
            lines.pop()
            omitted += 1
            omitted_line = f"- ... {omitted} 条较早的委派记录因上下文预算限制而从当前模型视图中省略"
        if _fits_budget(lines, omitted_line, max_chars):
            lines.append(omitted_line)

    rendered = "\n".join(lines)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max(0, max_chars - 4)] + "\n..."
