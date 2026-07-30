'未说明'

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from .message_format import format_tool_detail, format_tool_result, summarize_tool_title

# --------------------------------------------------------------------------- #
# Rows — the immutable units the transcript is built from.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UserRow:
    '未说明'
    text: str
    kind: Literal["user"] = "user"


@dataclass(frozen=True)
class AssistantRow:
    '未说明'
    text: str
    id: str | None = None
    error: bool = False
    kind: Literal["assistant"] = "assistant"


@dataclass(frozen=True)
class ToolRow:
    '未说明'
    tool_call_id: str
    tool_name: str
    title: str
    detail: str = ""
    result: str = ""
    status: Literal["running", "ok", "error"] = "running"
    kind: Literal["tool"] = "tool"


@dataclass(frozen=True)
class SystemRow:
    '未说明'
    text: str
    tone: Literal["info", "error"] = "info"
    kind: Literal["system"] = "system"


Row = UserRow | AssistantRow | ToolRow | SystemRow


# --------------------------------------------------------------------------- #
# Actions — the only ways the state can change.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UserSubmitted:
    '未说明'
    text: str


@dataclass(frozen=True)
class RunStarted:
    '未说明'
    pass


@dataclass(frozen=True)
class RunEnded:
    '未说明'
    usage: dict | None = None


@dataclass(frozen=True)
class AssistantDelta:
    '未说明'
    id: str
    text: str


@dataclass(frozen=True)
class AssistantError:
    '未说明'
    text: str


@dataclass(frozen=True)
class ToolStarted:
    '未说明'
    tool_call_id: str
    tool_name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    '未说明'
    tool_call_id: str
    content: str
    is_error: bool = False
    tool_name: str = ""


@dataclass(frozen=True)
class SystemMessage:
    '未说明'
    text: str
    tone: Literal["info", "error"] = "info"


@dataclass(frozen=True)
class ThreadTitle:
    '未说明'
    title: str


@dataclass(frozen=True)
class ClearRows:
    '未说明'
    pass


Action = UserSubmitted | RunStarted | RunEnded | AssistantDelta | AssistantError | ToolStarted | ToolResult | SystemMessage | ThreadTitle | ClearRows


# --------------------------------------------------------------------------- #
# State.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ViewState:
    '未说明'
    rows: tuple[Row, ...] = ()
    streaming: bool = False
    usage: dict | None = None
    title: str | None = None
    # Id of the message currently being generated this turn. Only this row renders
    # as plain text while streaming; everything else (history) stays Markdown.
    streaming_id: str | None = None
    # Row index of the *anonymous* (empty-id) assistant row receiving deltas this
    # turn, if any. A genuine id is a reliable cross-chunk key (see
    # `_apply_assistant_delta`'s whole-transcript id scan), but an empty id ("" —
    # see `runtime._as_str`) is shared by every id-less chunk from every turn, so
    # it cannot be matched the same way: scanning for `row.id == ""` would fold a
    # brand new turn's text into whatever earlier turn's row happened to be
    # id-less too. This index instead pins "this turn's" anonymous row by
    # position, reset alongside `streaming_id` at the start/end of every turn.
    streaming_anonymous_row_index: int | None = None


def initial_state(rows: tuple[Row, ...] = ()) -> ViewState:
    '未说明'
    return ViewState(rows=tuple(rows))


# --------------------------------------------------------------------------- #
# Reducer.
# --------------------------------------------------------------------------- #


def _append(state: ViewState, row: Row) -> ViewState:
    '未说明'
    return replace(state, rows=state.rows + (row,))


def reduce(state: ViewState, action: Action) -> ViewState:
    '未说明'

    if isinstance(action, UserSubmitted):
        return _append(state, UserRow(text=action.text))

    if isinstance(action, RunStarted):
        # New turn: no message is actively streaming yet (the client re-emits
        # prior messages first; those must not be treated as the active one).
        return replace(state, streaming=True, streaming_id=None, streaming_anonymous_row_index=None)

    if isinstance(action, RunEnded):
        return replace(
            state,
            streaming=False,
            streaming_id=None,
            streaming_anonymous_row_index=None,
            usage=action.usage if action.usage is not None else state.usage,
        )

    if isinstance(action, AssistantDelta):
        return _apply_assistant_delta(state, action)

    if isinstance(action, AssistantError):
        return _append(state, AssistantRow(text=action.text, error=True))

    if isinstance(action, ToolStarted):
        return _apply_tool_started(state, action)

    if isinstance(action, ToolResult):
        return _apply_tool_result(state, action)

    if isinstance(action, SystemMessage):
        return _append(state, SystemRow(text=action.text, tone=action.tone))

    if isinstance(action, ThreadTitle):
        return replace(state, title=action.title)

    if isinstance(action, ClearRows):
        return replace(state, rows=(), title=None, streaming_id=None, streaming_anonymous_row_index=None)

    return state


def _apply_assistant_delta(state: ViewState, action: AssistantDelta) -> ViewState:
    '未说明'
    if not action.id:
        return _apply_assistant_delta_anonymous(state, action)

    rows = list(state.rows)
    for i, row in enumerate(rows):
        # ``not row.error``: error rows are appended without an id, so they never
        # match here anyway — the guard is belt-and-suspenders to keep an error
        # row from being merged into if a future change ever gives it an id.
        if isinstance(row, AssistantRow) and row.id == action.id and not row.error:
            # Exact re-send of the same full text (e.g. a values snapshot
            # re-emitting history after reconnection): no-op.  Only multi-char
            # matches are treated as re-sends so single-char deltas that happen
            # to equal the buffer (CJK reduplication) are NOT mistaken for no-ops.
            if row.text == action.text and len(action.text) > 1:
                return state
            merged = _merge_stream_text(row.text, action.text)
            rows[i] = replace(row, text=merged)
            return _mark_streaming(replace(state, rows=tuple(rows)), action.id)
    return _mark_streaming(_append(state, AssistantRow(text=action.text, id=action.id)), action.id)


def _apply_assistant_delta_anonymous(state: ViewState, action: AssistantDelta) -> ViewState:
    '未说明'
    index = state.streaming_anonymous_row_index
    if index is not None and index == len(state.rows) - 1:
        row = state.rows[index]
        if isinstance(row, AssistantRow) and not row.error:
            # Same no-op / merge semantics as the id-keyed path above.
            if row.text == action.text and len(action.text) > 1:
                return state
            rows = list(state.rows)
            merged = _merge_stream_text(row.text, action.text)
            rows[index] = replace(row, text=merged)
            return _mark_streaming_anonymous(replace(state, rows=tuple(rows)), index)

    new_state = _append(state, AssistantRow(text=action.text, id=action.id))
    return _mark_streaming_anonymous(new_state, len(new_state.rows) - 1)


def _mark_streaming(state: ViewState, message_id: str) -> ViewState:
    '未说明'
    if state.streaming:
        return replace(state, streaming_id=message_id)
    return state


def _mark_streaming_anonymous(state: ViewState, index: int) -> ViewState:
    '未说明'
    if state.streaming:
        return replace(state, streaming_id=None, streaming_anonymous_row_index=index)
    return state


def _merge_stream_text(existing: str, incoming: str) -> str:
    '未说明'
    if not existing:
        return incoming
    # Cumulative re-delivery: incoming strictly extends existing.
    if len(incoming) > len(existing) and incoming.startswith(existing):
        return incoming
    # Stale/shorter re-send: existing already contains incoming as a prefix
    # (e.g. a values snapshot re-emitting history that has already been
    # accumulated from deltas). Only treat as stale when strictly shorter.
    if len(existing) > len(incoming) and existing.startswith(incoming):
        return existing
    return existing + incoming  # genuine incremental delta


def _apply_tool_started(state: ViewState, action: ToolStarted) -> ViewState:
    '未说明'
    if not action.tool_call_id:
        return state

    rows = list(state.rows)
    for i, row in enumerate(rows):
        if isinstance(row, ToolRow) and row.tool_call_id == action.tool_call_id:
            name = action.tool_name or row.tool_name
            detail = format_tool_detail(name, action.args) or row.detail
            rows[i] = replace(row, tool_name=name, title=summarize_tool_title(name), detail=detail)
            return replace(state, rows=tuple(rows))

    return _append(
        state,
        ToolRow(
            tool_call_id=action.tool_call_id,
            tool_name=action.tool_name,
            title=summarize_tool_title(action.tool_name),
            detail=format_tool_detail(action.tool_name, action.args),
            status="running",
        ),
    )


def _apply_tool_result(state: ViewState, action: ToolResult) -> ViewState:
    '未说明'
    if not action.tool_call_id:
        return state

    rows = list(state.rows)
    for i, row in enumerate(rows):
        if isinstance(row, ToolRow) and row.tool_call_id == action.tool_call_id:
            rows[i] = replace(
                row,
                status="error" if action.is_error else "ok",
                result=format_tool_result(action.content),
            )
            return replace(state, rows=tuple(rows))

    # No matching tool card (started chunks missed) -> surface the result anyway.
    return _append(
        state,
        ToolRow(
            tool_call_id=action.tool_call_id,
            tool_name=action.tool_name,
            title=summarize_tool_title(action.tool_name),
            status="error" if action.is_error else "ok",
            result=format_tool_result(action.content),
        ),
    )
