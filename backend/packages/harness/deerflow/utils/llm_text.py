"""处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""

from __future__ import annotations

import re

# Matches a complete <think>...</think> block (case-insensitive, spans newlines).
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
# Matches a dangling, unclosed <think> (model truncated at max_tokens mid-thought).
_OPEN_THINK_RE = re.compile(r"<think\b[^>]*>", re.IGNORECASE)


def strip_think_blocks(text: str, *, truncate_unclosed: bool = True) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    text = _THINK_BLOCK_RE.sub("", text)
    if truncate_unclosed:
        open_match = _OPEN_THINK_RE.search(text)
        if open_match:
            text = text[: open_match.start()]
    return text.strip()


def strip_markdown_code_fence(text: str) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_response_text(content: object) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)
