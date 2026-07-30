"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.tools.mcp_metadata import MCP_TOOL_METADATA_KEY, MCP_TOOL_ROUTING_METADATA_KEY, get_mcp_routing, tag_mcp_routing, tag_mcp_tool


class _Args(BaseModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    query: str = Field(..., description="query")


def _tool(name: str = "postgres_query") -> StructuredTool:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    async def _call(query: str) -> str:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return query

    return StructuredTool(
        name=name,
        description="Query internal data",
        args_schema=_Args,
        coroutine=_call,
    )


def test_tag_mcp_routing_preserves_existing_mcp_flag():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    tool = tag_mcp_tool(_tool())

    tagged = tag_mcp_routing(
        tool,
        {
            "mode": "prefer",
            "priority": 80,
            "keywords": ["订单"],
        },
    )

    assert tagged.metadata[MCP_TOOL_METADATA_KEY] is True
    assert tagged.metadata[MCP_TOOL_ROUTING_METADATA_KEY]["priority"] == 80
    assert get_mcp_routing(tagged)["keywords"] == ["订单"]


def test_get_mcp_routing_returns_none_for_non_mcp_tools():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    tool = tag_mcp_routing(
        _tool(),
        {
            "mode": "prefer",
            "priority": 80,
            "keywords": ["订单"],
        },
    )

    assert get_mcp_routing(tool) is None


def test_get_mcp_routing_returns_none_for_off_mode():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    tool = tag_mcp_tool(_tool())
    tag_mcp_routing(
        tool,
        {
            "mode": "off",
            "priority": 80,
            "keywords": ["订单"],
        },
    )

    assert get_mcp_routing(tool) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "stdio"])
async def test_get_mcp_tools_tags_effective_routing_metadata(transport: str):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.mcp.tools import get_mcp_tools

    tool = _tool("postgres_query")
    extensions_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "postgres": {
                    "type": transport,
                    "url": "http://localhost:8000/mcp",
                    "command": "npx",
                    "routing": {
                        "mode": "prefer",
                        "priority": 50,
                        "keywords": ["database"],
                    },
                    "tools": {
                        "query": {
                            "routing": {
                                "priority": 100,
                                "keywords": ["查库"],
                            }
                        }
                    },
                }
            }
        }
    )

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch(
            "deerflow.mcp.tools.build_servers_config",
            return_value={"postgres": {"transport": transport, "url": "http://localhost:8000/mcp", "command": "npx"}},
        ),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
    ):
        MockClient.return_value.get_tools = AsyncMock(return_value=[tool])
        tools = await get_mcp_tools()

    routing = get_mcp_routing(tools[0])
    assert routing is not None
    assert routing["priority"] == 100
    assert routing["keywords"] == ["查库"]
