'''解析输入中的技能斜杠命令，并匹配已启用且允许使用的技能。'''

from __future__ import annotations

import re
from dataclasses import dataclass

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.types import Skill

RESERVED_SLASH_SKILL_NAMES = frozenset({"bootstrap", "goal", "help", "memory", "models", "new", "status"})
_SLASH_SKILL_RE = re.compile(r"^/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)")


@dataclass(frozen=True, slots=True)
class SlashSkillReference:
    '''保存解析出的技能名称以及斜杠命令后剩余的任务文本。'''

    name: str
    remaining_text: str


@dataclass(frozen=True, slots=True)
class ResolvedSlashSkill:
    '''保存已匹配的技能、剩余任务文本及其运行时文件路径。'''

    skill: Skill
    remaining_text: str
    container_file_path: str


def parse_slash_skill_reference(text: str) -> SlashSkillReference | None:
    '''解析严格的 `/skill-name task` 输入，并忽略保留的控制命令。'''
    match = _SLASH_SKILL_RE.match(text)
    if not match:
        return None
    name = match.group(1)
    if name in RESERVED_SLASH_SKILL_NAMES:
        return None
    return SlashSkillReference(
        name=name,
        remaining_text=text[match.end() :].lstrip(),
    )


def resolve_slash_skill(
    text: str,
    skills: list[Skill],
    *,
    available_skills: set[str] | None = None,
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
) -> ResolvedSlashSkill | None:
    '''将斜杠输入解析为可运行的技能；保留命令、未启用或不可用时返回 ``None``。'''
    reference = parse_slash_skill_reference(text)
    if reference is None:
        return None
    if available_skills is not None and reference.name not in available_skills:
        return None

    skill = next((candidate for candidate in skills if candidate.name == reference.name and candidate.enabled), None)
    if skill is None:
        return None

    return ResolvedSlashSkill(
        skill=skill,
        remaining_text=reference.remaining_text,
        container_file_path=skill.get_container_file_path(container_base_path),
    )
