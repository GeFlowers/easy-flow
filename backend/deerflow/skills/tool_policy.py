'''根据技能声明过滤智能体可调用的工具，同时保留框架必需工具。'''

import logging
from typing import Protocol

from deerflow.skills.types import Skill

logger = logging.getLogger(__name__)


class NamedTool(Protocol):
    '''描述过滤器所需的最小工具接口：工具必须具有名称。'''

    name: str


ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES = frozenset({"read_file", "review_skill_package"})


def allowed_tool_names_for_skills(skills: list[Skill]) -> set[str] | None:
    '''合并已加载技能显式声明的工具白名单。

        未有任何技能声明白名单时返回 ``None``，表示沿用旧版放行行为。
        一旦存在显式声明，未声明的技能不再扩大权限。
    '''
    if not skills:
        return None

    allowed: set[str] = set()
    has_explicit_declaration = False
    for skill in skills:
        if skill.allowed_tools is None:
            continue
        has_explicit_declaration = True
        if not skill.allowed_tools:
            logger.info("Skill %s declared empty allowed-tools", skill.name)
        allowed.update(skill.allowed_tools)

    if not has_explicit_declaration:
        return None
    return allowed


def filter_tools_by_skill_allowed_tools[ToolT: NamedTool](
    tools: list[ToolT],
    skills: list[Skill],
    *,
    always_allowed_tool_names: set[str] | frozenset[str] = frozenset(),
) -> list[ToolT]:
    '''按技能白名单过滤工具，并保留调用方指定的框架级必需工具。'''
    allowed = allowed_tool_names_for_skills(skills)
    if allowed is None:
        return tools

    allowed_with_framework_tools = allowed | set(always_allowed_tool_names)
    return [tool for tool in tools if tool.name in allowed_with_framework_tools]
