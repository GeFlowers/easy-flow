'''把客户端流事件转换成终端视图动作，并将异常呈现为可显示的运行结果。'''

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from .view_state import (
    Action,
    AssistantDelta,
    AssistantError,
    RunEnded,
    RunStarted,
    ThreadTitle,
    ToolResult,
    ToolStarted,
)


class _StreamEventLike(Protocol):
    '''描述终端流解析器需要读取的事件类型和数据载荷。'''

    type: str
    data: dict


class _ClientLike(Protocol):
    '''定义终端客户端的流式调用接口，便于复用和替换客户端实现。'''

    def stream(self, message: str, *, thread_id: str | None = None, **kwargs: Any) -> Iterator[Any]:
        '''按消息、线程和其他运行参数产生流式事件。'''


def translate(event: _StreamEventLike) -> list[Action]:
    '''将客户端事件转换为助手增量、工具结果、标题或运行完成动作。'''
    if event.type == "messages-tuple":
        return _translate_message(event.data)
    if event.type == "end":
        usage = event.data.get("usage") if isinstance(event.data, dict) else None
        return [RunEnded(usage=usage)]
    if event.type == "values" and isinstance(event.data, dict):
        title = event.data.get("title")
        if isinstance(title, str) and title.strip():
            return [ThreadTitle(title=title.strip())]
        return []
    return []


def _translate_message(data: Any) -> list[Action]:
    '''解析消息事件中的助手文本和工具调用或工具执行结果。'''
    if not isinstance(data, dict):
        return []

    message_type = data.get("type")
    actions: list[Action] = []

    if message_type == "ai":
        text = _extract_text(data.get("content"))
        if text:
            actions.append(AssistantDelta(id=_as_str(data.get("id")), text=text))
        for tool_call in data.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            actions.append(
                ToolStarted(
                    tool_call_id=_as_str(tool_call.get("id")),
                    tool_name=_as_str(tool_call.get("name")),
                    args=tool_call.get("args") or {},
                )
            )
    elif message_type == "tool":
        is_error = bool(data.get("is_error")) or data.get("status") == "error"
        actions.append(
            ToolResult(
                tool_call_id=_as_str(data.get("tool_call_id")),
                content=_extract_text(data.get("content")),
                is_error=is_error,
                tool_name=_as_str(data.get("name")),
            )
        )

    return actions


def _as_str(value: Any) -> str:
    '''将可选值转换为文本，避免空标识被错误格式化为字符串 None。'''
    return "" if value is None else str(value)


def stream_actions(client: _ClientLike, message: str, *, thread_id: str | None = None, **kwargs: Any) -> Iterator[Action]:
    '''发出运行开始动作，再逐个转换客户端事件，并将异常映射为界面错误。'''
    yield RunStarted()
    try:
        for event in client.stream(message, thread_id=thread_id, **kwargs):
            yield from translate(event)
            if event.type == "end":
                return
        yield RunEnded()
    except Exception as exc:  # noqa: BLE001 - surface any model/runtime error in-UI
        yield AssistantError(str(exc) or exc.__class__.__name__)
        yield RunEnded()


def _extract_text(content: Any) -> str:
    '''从纯文本或多模态内容块中提取文本片段。'''
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content)
