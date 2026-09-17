"定义 tool_policy 模块提供的职责与可复用接口"

import logging
from typing import Protocol

from deerflow.skills.types import Skill

logger = logging.getLogger(__name__)


class NamedTool(Protocol):
    "封装 NamedTool 的状态、协作关系与公开操作"

    name: str


# Framework built-ins that remain available even when an active skill declares
# allowed-tools. They support controlled framework workflows rather than
# extending the reviewed/activated skill's own tool authority.
ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES = frozenset({"read_file", "review_skill_package"})


def allowed_tool_names_for_skills(skills: list[Skill]) -> set[str] | None:
    """执行 allowed_tool_names_for_skills 的明确职责，并返回与调用约定一致的结果。

    Return the union of explicit skill allowed-tools declarations.

        None means legacy allow-all behavior. It is returned only when no loaded
        skill declares allowed-tools. Once any skill declares the field, legacy
        skills without the field contribute no tools instead of disabling the
        explicit restrictions from other skills.
    """
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
    "执行 filter_tools_by_skill_allowed_tools 的明确职责，并返回与调用约定一致的结果"
    allowed = allowed_tool_names_for_skills(skills)
    if allowed is None:
        return tools

    allowed_with_framework_tools = allowed | set(always_allowed_tool_names)
    return [tool for tool in tools if tool.name in allowed_with_framework_tools]
