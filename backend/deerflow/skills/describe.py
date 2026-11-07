'''构建按需读取技能详情的工具，并生成供代理发现和加载技能的提示片段。'''

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

if TYPE_CHECKING:
    from langchain.tools import BaseTool

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.catalog import SkillCatalog
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)




@dataclass(frozen=True)
class SkillSearchSetup:
    '''保存技能详情工具和可用技能名称集合，供代理提示与工具注册流程共用。'''

    describe_skill_tool: BaseTool | None
    skill_names: frozenset[str]


def build_describe_skill_tool(
    catalog: SkillCatalog,
    *,
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
) -> BaseTool:
    '''创建技能详情工具；调用时搜索目录并返回匹配技能的描述、权限和容器内路径。'''

    @tool
    def describe_skill(
        name: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        '''根据代理提供的技能名搜索目录并返回匹配项的安全转义元数据。'''
        matched = catalog.search(name)
        if not matched:
            content = f"未找到匹配的技能： {name}"
        else:
            content = _render_skill_metadata(matched, container_base_path)

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_call_id,
                        name="describe_skill",
                    )
                ],
            }
        )

    return describe_skill


def build_skill_search_setup(
    skills: list,
    *,
    enabled: bool,
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
) -> SkillSearchSetup:
    '''在功能启用且存在技能时创建目录和详情工具，否则返回空配置。'''
    if not enabled or not skills:
        return SkillSearchSetup(None, frozenset())

    catalog = SkillCatalog(tuple(skills))
    return SkillSearchSetup(
        describe_skill_tool=build_describe_skill_tool(
            catalog,
            container_base_path=container_base_path,
        ),
        skill_names=catalog.names,
    )




def _render_skill_metadata(skills: list, container_base_path: str) -> str:
    '''将匹配技能的名称、描述、可用工具和容器路径整理为代理可读取的文本。'''
    blocks: list[str] = []
    for s in skills:
        mutability = "[自定义，可编辑]" if s.category == SkillCategory.CUSTOM else "[内置]"
        tools_line = ", ".join(s.allowed_tools) if s.allowed_tools else "(全部)"
        location = s.get_container_file_path(container_base_path)
        name = html.escape(s.name, quote=False)
        description = html.escape(s.description, quote=False)
        tools = html.escape(tools_line, quote=False)
        loc = html.escape(location, quote=False)
        blocks.append(f"## 技能： {name}\n- 描述： {description} {mutability}\n- 允许的工具： {tools}\n- 位置： {loc}")
    return "\n\n".join(blocks)




def get_skill_index_prompt_section(
    *,
    skill_names: frozenset[str] = frozenset(),
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
    skill_evolution_section: str = "",
) -> str:
    '''在提示中说明技能发现、详情读取和斜杠激活流程，并列出当前可用技能。'''
    if not skill_names:
        return ""

    names = ", ".join(html.escape(name, quote=False) for name in sorted(skill_names))
    evolution = f"\n{skill_evolution_section}" if skill_evolution_section else ""

    return f"""<skill_system>
你可以使用技能，为特定任务获得优化的工作流程。

**发现技能：**
1. 在 <skill_index> 中查找与任务匹配的技能名称
2. 调用 describe_skill(name) 获取技能描述和能力说明
3. 若技能适合任务，对返回的位置调用 read_file 以加载完整说明
4. 严格遵循技能说明

**显式斜杠技能激活：**
- 若用户以 `/<skill-name>` 开始请求，表示用户显式指定了该技能。
- 运行时会注入已激活的技能内容；除非注入内容引用了你需要的辅助资源，否则不要再次对该 SKILL.md 调用 `read_file`。
{evolution}
<skill_index>
{names}
</skill_index>

技能所在位置： {container_base_path}
</skill_system>"""
