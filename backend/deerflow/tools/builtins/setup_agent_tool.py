'''提供创建并配置自定义代理的内置工具。'''

import logging

import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from deerflow.config.agents_config import validate_agent_name
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


@tool(parse_docstring=True)
def setup_agent(
    soul: str,
    description: str,
    runtime: Runtime,
    skills: list[str] | None = None,
) -> Command:
    '''创建或修改自定义代理的配置，并返回所需设置。

    Args:
        soul: 定义代理个性与行为的完整 SOUL.md 内容。
        description: 一行描述，说明代理执行的任务。
        skills: 可选的技能名称列表。None 表示使用全部已启用技能，空列表表示不使用技能。
    '''

    if not soul or not soul.strip():
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Error: soul content is empty; refusing to create agent with an empty SOUL.md",
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            }
        )

    agent_name: str | None = runtime.context.get("agent_name") if runtime.context else None
    agent_dir = None
    is_new_dir = False

    try:
        agent_name = validate_agent_name(agent_name)
        paths = get_paths()
        if agent_name:
            user_id = resolve_runtime_user_id(runtime)
            agent_dir = paths.user_agent_dir(user_id, agent_name)
        else:
            agent_dir = paths.base_dir
        is_new_dir = not agent_dir.exists()
        agent_dir.mkdir(parents=True, exist_ok=True)

        if agent_name:
            config_data: dict = {"name": agent_name}
            if description:
                config_data["description"] = description
            if skills is not None:
                config_data["skills"] = skills

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text(soul, encoding="utf-8")

        logger.info(f"[agent_creator] Created agent '{agent_name}' at {agent_dir}")
        return Command(
            update={
                "created_agent_name": agent_name,
                "messages": [ToolMessage(content=f"Agent '{agent_name}' created successfully!", tool_call_id=runtime.tool_call_id)],
            }
        )

    except Exception as e:
        import shutil

        if agent_name and is_new_dir and agent_dir is not None and agent_dir.exists():
            shutil.rmtree(agent_dir)
        logger.error(f"[agent_creator] Failed to create agent '{agent_name}': {e}", exc_info=True)
        return Command(update={"messages": [ToolMessage(content=f"Error: {e}", tool_call_id=runtime.tool_call_id)]})
