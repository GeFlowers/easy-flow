'定义 test_deferred_promotion_integration 模块提供的职责与可复用接口。\n\nEnd-to-end: tool_search promotes a deferred tool into the next model turn.\n\nLocks the full loop through a real ``create_agent`` graph:\n  turn 1  -> deferred MCP tools hidden from bind_tools; model calls tool_search\n  ToolNode-> tool_search returns Command(update={"promoted": {...}}) -> state\n  turn 2  -> middleware reads state["promoted"] (hash-scoped) -> the searched\n             tool\'s schema is now bound; un-searched deferred tools stay hidden\n\nThis is the behavior #3272\'s redesign depends on (no ContextVar): promotion\nflows through graph state, so it works regardless of build/execute context.\n'

import asyncio

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.builtins.tool_search import build_deferred_tool_setup
from deerflow.tools.mcp_metadata import tag_mcp_tool


@as_tool
def active_tool(x: str) -> str:
    '执行 active_tool 的明确职责，并返回与调用约定一致的结果。\n\nAn always-active tool.'
    return x


@as_tool
def mcp_calc(expression: str) -> str:
    '执行 mcp_calc 的明确职责，并返回与调用约定一致的结果。\n\nEvaluate arithmetic.'
    return expression


@as_tool
def mcp_other(x: str) -> str:
    '执行 mcp_other 的明确职责，并返回与调用约定一致的结果。\n\nAnother deferred MCP tool.'
    return x


def test_tool_search_promotes_into_next_turn():
    '验证 tool、search、promotes、into、next、turn 场景下的预期行为、边界条件与结果'
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        '封装 RecordingModel 的状态、协作关系与公开操作'
        def bind_tools(self, tools, **kwargs):
            '执行 bind_tools 的明确职责，并返回与调用约定一致的结果'
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    setup = build_deferred_tool_setup([active_tool, tag_mcp_tool(mcp_calc), tag_mcp_tool(mcp_other)], enabled=True)
    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))

    graph = create_agent(
        model=model,
        tools=[active_tool, mcp_calc, mcp_other, setup.tool_search_tool],
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="use the deferred calculator")]}))

    assert len(bound) >= 2, f"expected >=2 model binds, got {bound}"
    # 第 1 回合：两个延迟 MCP 工具均已隐藏。
    assert "mcp_calc" not in bound[0] and "mcp_other" not in bound[0]
    # 第2轮：搜索到的工具被提升（可见）；未搜索的则保持隐藏状态。
    assert "mcp_calc" in bound[1]
    assert "mcp_other" not in bound[1]
    # 促销记录在图状态中，范围由目录哈希确定。
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["mcp_calc"]}
