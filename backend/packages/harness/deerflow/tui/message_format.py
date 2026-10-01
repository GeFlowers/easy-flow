'''将工具名称、参数和返回内容整理为适合终端显示的简短文本。'''

from __future__ import annotations

import json
from typing import Any

_TOOL_TITLES: dict[str, str] = {
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "str_replace": "Edit",
    "bash": "Bash",
    "shell": "Shell",
    "command": "Run",
    "web_search": "Search",
    "web_fetch": "Fetch",
    "todo_write": "Todo",
    "task": "Subagent",
    "ls": "List",
    "glob": "Find",
    "grep": "Search",
}

_DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    "read_file": ("path", "file_path", "filename"),
    "write_file": ("path", "file_path", "filename"),
    "edit_file": ("path", "file_path", "filename"),
    "bash": ("command", "cmd"),
    "shell": ("command", "cmd"),
    "command": ("command", "cmd"),
    "web_search": ("query", "q"),
    "grep": ("pattern", "query"),
    "glob": ("pattern",),
    "web_fetch": ("url",),
}

_GENERIC_DETAIL_KEYS = ("path", "file_path", "command", "query", "url", "pattern", "name")

DEFAULT_DETAIL_LIMIT = 80
DEFAULT_RESULT_LIMIT = 160


def truncate(text: str, limit: int) -> str:
    '''按字符数裁剪过长文本，并用省略号标示内容被截断。'''
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def summarize_tool_title(tool_name: str) -> str:
    '''优先返回内置工具的友好标题，未知工具名则转换为可读形式。'''
    if not tool_name or not tool_name.strip():
        return "Tool"
    if tool_name in _TOOL_TITLES:
        return _TOOL_TITLES[tool_name]
    return _humanize(tool_name)


def format_tool_detail(tool_name: str, args: Any, limit: int = DEFAULT_DETAIL_LIMIT) -> str:
    '''从工具参数中挑选最有代表性的字段，压缩为单行并限制长度。'''
    if not isinstance(args, dict) or not args:
        return ""

    keys = _DETAIL_KEYS.get(tool_name, ()) + _GENERIC_DETAIL_KEYS
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return truncate(_one_line(value), limit)

    try:
        compact = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        compact = str(args)
    return truncate(compact, limit)


def format_tool_result(result: Any, limit: int = DEFAULT_RESULT_LIMIT) -> str:
    '''将工具结果转换为单行文本，必要时先序列化结构化值再裁剪。'''
    if result is None:
        return ""
    if not isinstance(result, str):
        try:
            result = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            result = str(result)
    return truncate(_one_line(result), limit)


def _one_line(text: str) -> str:
    '''折叠连续空白字符，使多行内容适合内联显示。'''
    return " ".join(text.split())


def _humanize(name: str) -> str:
    '''将下划线和连字符分隔的工具名转换为首字母大写的标题。'''
    cleaned = name.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return name
    return " ".join(word[:1].upper() + word[1:] for word in cleaned.split())
