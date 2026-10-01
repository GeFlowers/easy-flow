'''解析技能 Markdown 文件头部的 YAML 元数据，并保留原始头部和正文供后续校验。'''

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

ALLOWED_FRONTMATTER_PROPERTIES = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "required-secrets",
    "secrets-autonomous",
    "metadata",
    "compatibility",
    "version",
    "author",
}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True)
class SkillMarkdownParts:
    '''保存解析后的元数据、YAML 原文和 frontmatter 后的 Markdown 正文。'''

    metadata: dict[str, Any]
    frontmatter_text: str
    body: str


def split_skill_markdown(content: str) -> tuple[SkillMarkdownParts | None, str | None]:
    '''拆分技能说明中的 YAML frontmatter 与正文；格式、YAML 或顶层类型错误时返回原因。'''
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None, "No YAML frontmatter found"

    frontmatter_text = match.group(1)
    try:
        metadata = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        return None, f"Invalid YAML in frontmatter: {exc}"

    if not isinstance(metadata, dict):
        return None, "Frontmatter must be a YAML dictionary"

    return (
        SkillMarkdownParts(
            metadata=metadata,
            frontmatter_text=frontmatter_text,
            body=content[match.end() :],
        ),
        None,
    )
