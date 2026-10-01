'''从工具调用和读取结果中识别已加载技能，并生成精简的后续上下文提醒。'''

from __future__ import annotations

import logging
import posixpath
import re
from collections.abc import Collection, Mapping
from html import escape
from typing import Any, TypedDict

import yaml
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from deerflow.agents.thread_state import _SKILL_DESCRIPTION_MAX_CHARS, SkillEntry

_SKILL_FILE_NAME = "SKILL.md"
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SKILL_CONTEXT_ENTRY_KEY = "skill_context_entry"
logger = logging.getLogger(__name__)


class SkillEntryMetadata(TypedDict):
    '''保存经验证的技能说明文件路径及其描述。'''

    path: str
    description: str


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    '''兼容标准和旧式工具调用结构，提取工具名称。'''
    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return ""


def _tool_call_id(tool_call: dict[str, Any]) -> str | None:
    '''从工具调用中提取可配对结果消息的调用标识。'''
    tool_call_id = tool_call.get("id")
    return str(tool_call_id) if tool_call_id else None


def _tool_call_path(tool_call: dict[str, Any]) -> str | None:
    '''从工具参数的常见路径字段中提取文件地址。'''
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return None
    for key in ("path", "file_path", "filepath"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _normalize_under_root(path: str, normalized_root: str) -> str | None:
    '''规范化路径，并仅在其位于技能根目录内时返回结果。'''
    normalized = posixpath.normpath(path)
    if normalized == normalized_root or normalized.startswith(normalized_root + "/"):
        return normalized
    return None


def _is_skill_file(path: str) -> bool:
    '''判断路径末尾是否为技能主说明文件 ``SKILL.md``。'''
    return posixpath.basename(path) == _SKILL_FILE_NAME


def _skill_name_from_path(skill_md_path: str) -> str:
    '''从 ``SKILL.md`` 所在目录名称取得技能名。'''
    return posixpath.basename(posixpath.dirname(skill_md_path))


def _parse_description(content: str) -> str:
    '''解析技能说明文件前置元数据中的描述，并折叠空白和限制长度。'''
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        return ""
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return ""
    if not isinstance(metadata, dict):
        return ""
    description = metadata.get("description")
    if not isinstance(description, str):
        return ""
    return " ".join(description.split())[:_SKILL_DESCRIPTION_MAX_CHARS]


def _is_tool_error_text(content: str) -> bool:
    '''识别以工具错误前缀开头的读取结果。'''
    return content.lstrip().startswith("Error:")


def build_skill_entry_metadata_from_read(
    path: str,
    content: str,
    *,
    skills_root: str,
) -> SkillEntryMetadata | None:
    '''验证读取路径和结果后构建技能元数据；非技能文件或错误结果返回 ``None``。'''
    normalized_root = posixpath.normpath(skills_root.rstrip("/") or "/")
    normalized_path = _normalize_under_root(path, normalized_root)
    if normalized_path is None or not _is_skill_file(normalized_path) or _is_tool_error_text(content):
        return None
    return {
        "path": normalized_path,
        "description": _parse_description(content),
    }


def read_skill_entry_metadata(additional_kwargs: Mapping[str, object] | None) -> SkillEntryMetadata | None:
    '''从工具结果附加字段中读取并规范化已验证的技能元数据。'''
    if not additional_kwargs:
        return None
    raw = additional_kwargs.get(SKILL_CONTEXT_ENTRY_KEY)
    if not isinstance(raw, Mapping):
        return None
    path = raw.get("path")
    description = raw.get("description")
    if not isinstance(path, str):
        return None
    return {
        "path": path,
        "description": " ".join(description.split())[:_SKILL_DESCRIPTION_MAX_CHARS] if isinstance(description, str) else "",
    }


def _escape_context_text(value: object) -> str:
    '''转义上下文中的特殊字符，避免内容改变生成的标记结构。'''
    return escape(str(value), quote=False)


def extract_skills(
    messages: list[AnyMessage],
    *,
    skills_root: str,
    read_tool_names: Collection[str],
) -> list[SkillEntry]:
    '''配对技能文件读取调用和成功结果，只记录根目录内且元数据匹配的技能。'''
    normalized_root = posixpath.normpath(skills_root.rstrip("/") or "/")
    read_names = frozenset(read_tool_names)

    skill_paths_by_id: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls or []:
            if _tool_call_name(tool_call) not in read_names:
                continue
            tool_call_id = _tool_call_id(tool_call)
            raw_path = _tool_call_path(tool_call)
            path = _normalize_under_root(raw_path, normalized_root) if raw_path else None
            if tool_call_id and path and _is_skill_file(path):
                skill_paths_by_id[tool_call_id] = path

    entries: list[SkillEntry] = []
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "status", "success") == "error":
            continue
        tool_call_id = str(message.tool_call_id) if message.tool_call_id else ""
        expected_path = skill_paths_by_id.get(tool_call_id)
        if expected_path is None:
            continue
        metadata = read_skill_entry_metadata(message.additional_kwargs)
        if metadata is None:
            content = message.content if isinstance(message.content, str) else ""
            if not _is_tool_error_text(content):
                logger.warning("missing skill read metadata: tool_call_id=%s path=%s", tool_call_id, expected_path)
            continue
        if metadata["path"] != expected_path:
            logger.warning(
                "mismatched skill read metadata: tool_call_id=%s expected_path=%s metadata_path=%s",
                tool_call_id,
                expected_path,
                metadata["path"],
            )
            continue
        entries.append(
            {
                "name": _skill_name_from_path(expected_path),
                "path": expected_path,
                "description": metadata["description"],
                "loaded_at": index,
            }
        )
    return entries


def render_skill_context(entries: list[SkillEntry]) -> str:
    '''把已加载技能整理为名称、描述和路径清单，不重复插入技能正文。'''
    if not entries:
        return ""

    lines = ["## Active skills (loaded earlier - re-read the file before applying its instructions)"]
    for entry in entries:
        name = _escape_context_text(entry["name"])
        path = _escape_context_text(entry["path"])
        raw_description = entry.get("description") or ""
        if isinstance(raw_description, str):
            raw_description = " ".join(raw_description.split())[:_SKILL_DESCRIPTION_MAX_CHARS]
        description = _escape_context_text(raw_description)
        suffix = f": {description}" if description else ""
        lines.append(f"- {name}{suffix} -> {path}")
    return "\n".join(lines)
