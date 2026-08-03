#!/usr/bin/env python3
"""从环境变量和配置文件解析 uv 可选依赖参数。"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 与 uv 接受的可选依赖名称格式保持一致，避免来自 .env 或其他半可信来源的
# UV_EXTRAS 在 `uv sync --extra <name>` 参数中引入 Shell 元字符。
_EXTRA_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _validate_extras(names: list[str]) -> list[str]:
    """校验、规范化并去重 uv 可选依赖组名称。"""
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
    """解析环境变量中以逗号或空白分隔的可选依赖组。"""
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
    """移除配置行中位于引号外部的行尾注释。"""
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
    """去除配置值首尾成对的单引号或双引号。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def section_value(lines: list[str], section: str, key: str) -> str | None:
    """读取简单配置节中的指定键值。"""
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
    """读取嵌套配置节中的指定键值。"""
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

        # 匹配顶层配置节
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

        # 从第一个子项记录父配置节的内容缩进
        if parent_indent is None and indent > 0:
            parent_indent = indent

        # 缩进回到零时表示已离开父配置节
        if indent == 0:
            inside_parent = False
            inside_child = False
            continue

        # 判断当前行是否位于父配置节的直接子级
        if parent_indent is not None and indent == parent_indent:
            # 该行可能是子配置节，也可能是父配置节的直接键
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

        # 已进入目标子配置节，记录其内容缩进
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
    """按首次出现顺序合并并去重多组可选依赖。"""
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
    """合并运行时环境变量与配置文件中的 uv 可选依赖。"""
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
    """检测 uv 可选依赖并输出对应的命令行参数。"""
    extras = resolve_extras()
    if extras:
        sys.stdout.write(format_flags(extras))
    return 0


if __name__ == "__main__":
    sys.exit(main())
