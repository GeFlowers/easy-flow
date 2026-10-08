'''清理模型输出中的思考标签和代码围栏，并统一提取文本内容。'''

from __future__ import annotations

import re

# 匹配完整的思考标签区块，忽略大小写并允许跨行内容。
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
# 匹配未闭合的思考标签，用于截断模型输出中未完成的思考内容。
_OPEN_THINK_RE = re.compile(r"<think\b[^>]*>", re.IGNORECASE)


def strip_think_blocks(text: str, *, truncate_unclosed: bool = True) -> str:
    '''移除完整思考区块，并可选择丢弃未闭合标签之后的截断内容。'''
    text = _THINK_BLOCK_RE.sub("", text)
    if truncate_unclosed:
        open_match = _OPEN_THINK_RE.search(text)
        if open_match:
            text = text[: open_match.start()]
    return text.strip()


def strip_markdown_code_fence(text: str) -> str:
    '''去除包裹整段回答的 Markdown 代码围栏，不改动普通文本。'''
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_response_text(content: object) -> str:
    '''从字符串、分段文本块或空响应中提取适合展示和后续处理的文本。'''
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
