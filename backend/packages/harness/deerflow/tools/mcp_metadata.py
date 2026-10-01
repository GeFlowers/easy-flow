'''管理 MCP 工具来源与路由信息的元数据标记。'''

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.tools import BaseTool

MCP_TOOL_METADATA_KEY = "deerflow_mcp"
MCP_TOOL_ROUTING_METADATA_KEY = "deerflow_mcp_routing"


def tag_mcp_tool(tool: BaseTool) -> BaseTool:
    '''为工具写入 MCP 来源标记并返回该工具。'''
    tool.metadata = {**(tool.metadata or {}), MCP_TOOL_METADATA_KEY: True}
    return tool


def is_mcp_tool(tool: BaseTool) -> bool:
    '''判断工具是否带有 MCP 来源标记。'''
    return (getattr(tool, "metadata", None) or {}).get(MCP_TOOL_METADATA_KEY) is True


def tag_mcp_routing(tool: BaseTool, routing: Mapping[str, Any]) -> BaseTool:
    '''为 MCP 工具附加路由元数据并返回该工具。'''
    tool.metadata = {
        **(tool.metadata or {}),
        MCP_TOOL_ROUTING_METADATA_KEY: dict(routing),
    }
    return tool


def get_mcp_routing(tool: BaseTool) -> dict[str, Any] | None:
    '''仅当 MCP 工具的路由模式启用时返回其路由元数据。'''
    if not is_mcp_tool(tool):
        return None
    routing = (getattr(tool, "metadata", None) or {}).get(MCP_TOOL_ROUTING_METADATA_KEY)
    if not isinstance(routing, dict) or routing.get("mode") == "off":
        return None
    return routing
