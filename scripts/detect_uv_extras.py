#!/usr/bin/env python3
"""本脚本负责检测。安全边界：仅处理显式指定的输入与路径，不作为常驻生产服务入口。"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Mirrors uv's accepted shape for extra names — keeps the eventual
# `uv sync --extra <name>` invocation free of shell metacharacters even when
# `UV_EXTRAS` comes from `.env` or another semi-trusted source.
_EXTRA_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _validate_extras(names: list[str]) -> list[str]:
    '未说明'
    valid: list[str] = []
    for name in names:
        if _EXTRA_NAME_RE.match(name):
            valid.append(name)
        else:
            print(
                f"detect_uv_extras: ignoring invalid UV_EXTRAS entry {name!r} (must match [A-Za-z][A-Za-z0-9_-]*)",
                file=sys.stderr,
            )
    return valid


def parse_env_extras(value: str) -> list[str]:
    '未说明'
    parts = re.split(r"[\s,]+", value.strip())
    return _validate_extras([p for p in parts if p])


def find_config_file() -> Path | None:
    """执行配置 文件对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    explicit = os.environ.get("DEER_FLOW_CONFIG_PATH")
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
    for path in (Path("config.yaml"), Path("backend/config.yaml")):
        if path.is_file():
            return path
    return None


_SECTION_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*$")
_INDENTED_SECTION_RE = re.compile(r"^\s+([A-Za-z_][\w-]*)\s*:\s*$")
_KEY_RE = re.compile(r"^\s+([A-Za-z_][\w-]*)\s*:\s*(\S.*?)\s*$")


def _strip_comment(line: str) -> str:
    '未说明'
    in_quote: str | None = None
    out: list[str] = []
    for ch in line:
        if in_quote is not None:
            out.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _unquote(value: str) -> str:
    '未说明'
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def section_value(lines: list[str], section: str, key: str) -> str | None:
    '未说明'
    inside = False
    child_indent: int | None = None
    for raw in lines:
        line = _strip_comment(raw)
        if not line.strip():
            continue
        sect_match = _SECTION_RE.match(line)
        if sect_match:
            inside = sect_match.group(1) == section
            child_indent = None
            continue
        if not inside:
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 0:
            inside = False
            continue
        if child_indent is None:
            child_indent = indent
        if indent < child_indent:
            inside = False
            continue
        if indent != child_indent:
            continue
        key_match = _KEY_RE.match(line)
        if key_match and key_match.group(1) == key:
            return _unquote(key_match.group(2).strip())
    return None


def nested_section_value(lines: list[str], section_path: str, key: str) -> str | None:
    '未说明'
    parts = section_path.split(".")
    if len(parts) != 2:
        return None
    parent_section, child_section = parts

    inside_parent = False
    inside_child = False
    parent_indent: int | None = None
    child_indent: int | None = None

    for raw in lines:
        line = _strip_comment(raw)
        if not line.strip():
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Top-level section match
        sect_match = _SECTION_RE.match(line)
        if sect_match:
            if indent == 0:
                inside_parent = sect_match.group(1) == parent_section
            inside_child = False
            parent_indent = None
            child_indent = None
            continue

        if not inside_parent:
            continue

        # Track parent indent from first child
        if parent_indent is None and indent > 0:
            parent_indent = indent

        # If indent goes back to 0, we left the parent section
        if indent == 0:
            inside_parent = False
            inside_child = False
            continue

        # Check if we're at the parent's child level (subsection)
        if parent_indent is not None and indent == parent_indent:
            # This could be a subsection or a direct key of parent
            sub_match = _INDENTED_SECTION_RE.match(line)
            if sub_match and sub_match.group(1) == child_section:
                inside_child = True
                child_indent = None
                continue
            else:
                inside_child = False
                continue

        if not inside_child:
            continue

        # We're inside the subsection — track child indent
        if child_indent is None and indent > (parent_indent or 0):
            child_indent = indent

        if child_indent is not None and indent != child_indent:
            continue

        key_match = _KEY_RE.match(line)
        if key_match and key_match.group(1) == key:
            return _unquote(key_match.group(2).strip())

    return None


def detect_from_config(path: Path) -> list[str]:
    """执行检测 配置对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    extras: set[str] = set()
    if (section_value(lines, "database", "backend") or "").lower() == "postgres":
        extras.add("postgres")
    if (section_value(lines, "checkpointer", "type") or "").lower() == "postgres":
        extras.add("postgres")
    if (section_value(lines, "stream_bridge", "type") or "").lower() == "redis":
        extras.add("redis")
    if (nested_section_value(lines, "channels.discord", "enabled") or "").lower() == "true":
        extras.add("discord")
    return sorted(extras)


def detect_from_runtime_env() -> list[str]:
    """执行检测对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    extras: set[str] = set()
    if os.environ.get("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "").strip():
        extras.add("redis")
    return sorted(extras)


def merge_extras(*groups: list[str]) -> list[str]:
    '未说明'
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for extra in group:
            if extra in seen:
                continue
            seen.add(extra)
            merged.append(extra)
    return merged


def resolve_extras() -> list[str]:
    '未说明'
    runtime_env_extras = detect_from_runtime_env()
    env = os.environ.get("UV_EXTRAS", "")
    if env.strip():
        return merge_extras(parse_env_extras(env), runtime_env_extras)
    config = find_config_file()
    if config is None:
        return runtime_env_extras
    return merge_extras(detect_from_config(config), runtime_env_extras)


def format_flags(extras: list[str]) -> str:
    """执行格式对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    return " ".join(f"--extra {e}" for e in extras)


def main() -> int:
    '未说明'
    extras = resolve_extras()
    if extras:
        sys.stdout.write(format_flags(extras))
    return 0


if __name__ == "__main__":
    sys.exit(main())
