"""定义 skill_context 模块提供的职责与可复用接口。

Deterministic capture and rendering for loaded skill files."""

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
    "封装 SkillEntryMetadata 的状态、协作关系与公开操作"

    path: str
    description: str


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    "执行 _tool_call_name 的明确职责，并返回与调用约定一致的结果"
    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return ""


def _tool_call_id(tool_call: dict[str, Any]) -> str | None:
    "执行 _tool_call_id 的明确职责，并返回与调用约定一致的结果"
    tool_call_id = tool_call.get("id")
    return str(tool_call_id) if tool_call_id else None


def _tool_call_path(tool_call: dict[str, Any]) -> str | None:
    "执行 _tool_call_path 的明确职责，并返回与调用约定一致的结果"
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return None
    for key in ("path", "file_path", "filepath"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _normalize_under_root(path: str, normalized_root: str) -> str | None:
    "执行 _normalize_under_root 的明确职责，并返回与调用约定一致的结果"
    normalized = posixpath.normpath(path)
    if normalized == normalized_root or normalized.startswith(normalized_root + "/"):
        return normalized
    return None


def _is_skill_file(path: str) -> bool:
    "执行 _is_skill_file 的明确职责，并返回与调用约定一致的结果"
    return posixpath.basename(path) == _SKILL_FILE_NAME


def _skill_name_from_path(skill_md_path: str) -> str:
    """执行 _skill_name_from_path 的明确职责，并返回与调用约定一致的结果。

    Derive the skill name from the directory containing SKILL.md."""
    return posixpath.basename(posixpath.dirname(skill_md_path))


def _parse_description(content: str) -> str:
    """执行 _parse_description 的明确职责，并返回与调用约定一致的结果。

    Extract frontmatter description from already-read SKILL.md content."""
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
    "执行 _is_tool_error_text 的明确职责，并返回与调用约定一致的结果"
    return content.lstrip().startswith("Error:")


def build_skill_entry_metadata_from_read(
    path: str,
    content: str,
    *,
    skills_root: str,
) -> SkillEntryMetadata | None:
    "构建并返回，并遵守 build_skill_entry_metadata_from_read 所表达的接口约束"
    normalized_root = posixpath.normpath(skills_root.rstrip("/") or "/")
    normalized_path = _normalize_under_root(path, normalized_root)
    if normalized_path is None or not _is_skill_file(normalized_path) or _is_tool_error_text(content):
        return None
    return {
        "path": normalized_path,
        "description": _parse_description(content),
    }


def read_skill_entry_metadata(additional_kwargs: Mapping[str, object] | None) -> SkillEntryMetadata | None:
    "执行 read_skill_entry_metadata 的明确职责，并返回与调用约定一致的结果"
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
    "执行 _escape_context_text 的明确职责，并返回与调用约定一致的结果"
    return escape(str(value), quote=False)


def extract_skills(
    messages: list[AnyMessage],
    *,
    skills_root: str,
    read_tool_names: Collection[str],
) -> list[SkillEntry]:
    """执行 extract_skills 的明确职责，并返回与调用约定一致的结果。

    Enumerate skill-file reads (AI read_file call + paired ToolMessage result)."""
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
    """执行 render_skill_context 的明确职责，并返回与调用约定一致的结果。

    Render active-skill references as a compact reminder, not the body."""
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
