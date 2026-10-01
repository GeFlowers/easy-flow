'''定义终端对话的不可变行、事件动作、整体视图状态及其状态归约逻辑。'''

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from .message_format import format_tool_detail, format_tool_result, summarize_tool_title



@dataclass(frozen=True)
class UserRow:
    '''保存用户提交的一条对话文本。'''

    text: str
    kind: Literal["user"] = "user"


@dataclass(frozen=True)
class AssistantRow:
    '''保存代理生成的文本、消息标识和错误标记。'''

    text: str
    id: str | None = None
    error: bool = False
    kind: Literal["assistant"] = "assistant"


@dataclass(frozen=True)
class ToolRow:
    '''保存工具调用卡片的名称、参数摘要、执行状态和结果。'''

    tool_call_id: str
    tool_name: str
    title: str
    detail: str = ""
    result: str = ""
    status: Literal["running", "ok", "error"] = "running"
    kind: Literal["tool"] = "tool"


@dataclass(frozen=True)
class SystemRow:
    '''保存界面提示或错误说明及其语气。'''

    text: str
    tone: Literal["info", "error"] = "info"
    kind: Literal["system"] = "system"


Row = UserRow | AssistantRow | ToolRow | SystemRow




@dataclass(frozen=True)
class UserSubmitted:
    '''表示用户提交了一条待发送消息。'''

    text: str


@dataclass(frozen=True)
class RunStarted:
    '''表示一轮代理执行已经开始。'''

    pass


@dataclass(frozen=True)
class RunEnded:
    '''表示代理执行结束，并可携带本轮用量数据。'''

    usage: dict | None = None


@dataclass(frozen=True)
class AssistantDelta:
    '''表示收到一段代理回复增量及其消息标识。'''

    id: str
    text: str


@dataclass(frozen=True)
class AssistantError:
    '''表示代理运行发生错误，需在对话中展示说明。'''

    text: str


@dataclass(frozen=True)
class ToolStarted:
    '''表示工具开始执行，并携带工具调用标识和参数。'''

    tool_call_id: str
    tool_name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    '''表示工具调用已返回内容及成功或失败状态。'''

    tool_call_id: str
    content: str
    is_error: bool = False
    tool_name: str = ""


@dataclass(frozen=True)
class SystemMessage:
    '''表示需要追加到对话记录的系统提示。'''

    text: str
    tone: Literal["info", "error"] = "info"


@dataclass(frozen=True)
class ThreadTitle:
    '''表示线程标题已解析或更新。'''

    title: str


@dataclass(frozen=True)
class ClearRows:
    '''表示清除当前对话行和标题。'''

    pass


Action = UserSubmitted | RunStarted | RunEnded | AssistantDelta | AssistantError | ToolStarted | ToolResult | SystemMessage | ThreadTitle | ClearRows




@dataclass(frozen=True)
class ViewState:
    '''持有用于渲染的对话行、流式状态、标题和用量快照。'''

    rows: tuple[Row, ...] = ()
    streaming: bool = False
    usage: dict | None = None
    title: str | None = None
    streaming_id: str | None = None
    streaming_anonymous_row_index: int | None = None


def initial_state(rows: tuple[Row, ...] = ()) -> ViewState:
    '''创建带有可选历史行的初始终端视图状态。'''
    return ViewState(rows=tuple(rows))




def _append(state: ViewState, row: Row) -> ViewState:
    '''以不可变方式将一条新行追加到视图状态。'''
    return replace(state, rows=state.rows + (row,))


def reduce(state: ViewState, action: Action) -> ViewState:
    '''根据用户输入、运行事件和工具事件更新终端视图状态。'''

    if isinstance(action, UserSubmitted):
        return _append(state, UserRow(text=action.text))

    if isinstance(action, RunStarted):
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
    '''按消息标识合并代理流式文本，避免重复历史快照覆盖或重复追加。'''
    if not action.id:
        return _apply_assistant_delta_anonymous(state, action)

    rows = list(state.rows)
    for i, row in enumerate(rows):
        if isinstance(row, AssistantRow) and row.id == action.id and not row.error:
            if row.text == action.text and len(action.text) > 1:
                return state
            merged = _merge_stream_text(row.text, action.text)
            rows[i] = replace(row, text=merged)
            return _mark_streaming(replace(state, rows=tuple(rows)), action.id)
    return _mark_streaming(_append(state, AssistantRow(text=action.text, id=action.id)), action.id)


def _apply_assistant_delta_anonymous(state: ViewState, action: AssistantDelta) -> ViewState:
    '''合并没有稳定消息标识的代理文本，并仅在当前轮次复用匿名行。'''
    index = state.streaming_anonymous_row_index
    if index is not None and index == len(state.rows) - 1:
        row = state.rows[index]
        if isinstance(row, AssistantRow) and not row.error:
            if row.text == action.text and len(action.text) > 1:
                return state
            rows = list(state.rows)
            merged = _merge_stream_text(row.text, action.text)
            rows[index] = replace(row, text=merged)
            return _mark_streaming_anonymous(replace(state, rows=tuple(rows)), index)

    new_state = _append(state, AssistantRow(text=action.text, id=action.id))
    return _mark_streaming_anonymous(new_state, len(new_state.rows) - 1)


def _mark_streaming(state: ViewState, message_id: str) -> ViewState:
    '''当一轮运行仍在进行时记录当前正在生成的消息标识。'''
    if state.streaming:
        return replace(state, streaming_id=message_id)
    return state


def _mark_streaming_anonymous(state: ViewState, index: int) -> ViewState:
    '''记录当前轮次接收匿名代理增量的行位置。'''
    if state.streaming:
        return replace(state, streaming_id=None, streaming_anonymous_row_index=index)
    return state


def _merge_stream_text(existing: str, incoming: str) -> str:
    '''区分累计文本重发、较短的历史重放和真正的新流式片段。'''
    if not existing:
        return incoming
    if len(incoming) > len(existing) and incoming.startswith(existing):
        return incoming
    if len(existing) > len(incoming) and existing.startswith(incoming):
        return existing
    return existing + incoming


def _apply_tool_started(state: ViewState, action: ToolStarted) -> ViewState:
    '''按调用标识更新已有工具卡片，或为新工具调用追加运行中卡片。'''
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
    '''更新对应工具卡片的完成状态和返回内容；找不到卡片时补建结果卡片。'''
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
