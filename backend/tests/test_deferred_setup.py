'定义 test_deferred_setup 模块提供的职责与可复用接口'
from langchain_core.tools import tool as as_tool
from langgraph.types import Command

from deerflow.tools.builtins.tool_search import DeferredToolCatalog, build_deferred_tool_setup, build_tool_search_tool
from deerflow.tools.mcp_metadata import is_mcp_tool, tag_mcp_tool


@as_tool
def mcp_calc(expression: str) -> str:
    '执行 mcp_calc 的明确职责，并返回与调用约定一致的结果。\n\nEvaluate arithmetic.'
    return expression


@as_tool
def local_echo(text: str) -> str:
    '执行 local_echo 的明确职责，并返回与调用约定一致的结果。\n\nEcho text.'
    return text


def test_is_mcp_tool_reads_metadata():
    '验证 is、mcp、tool、reads、metadata 场景下的预期行为、边界条件与结果'
    assert is_mcp_tool(tag_mcp_tool(mcp_calc)) is True
    assert is_mcp_tool(local_echo) is False


def test_setup_disabled_returns_empty():
    '验证 setup、disabled、returns、empty 场景下的预期行为、边界条件与结果'
    setup = build_deferred_tool_setup([tag_mcp_tool(mcp_calc), local_echo], enabled=False)
    assert setup.tool_search_tool is None
    assert setup.deferred_names == frozenset()
    assert setup.catalog_hash is None


def test_setup_no_mcp_returns_empty():
    '验证 setup、no、mcp、returns、empty 场景下的预期行为、边界条件与结果'
    setup = build_deferred_tool_setup([local_echo], enabled=True)
    assert setup.tool_search_tool is None
    assert setup.deferred_names == frozenset()


def test_setup_builds_from_mcp_survivors():
    '验证 setup、builds、from、mcp、survivors 场景下的预期行为、边界条件与结果'
    setup = build_deferred_tool_setup([tag_mcp_tool(mcp_calc), local_echo], enabled=True)
    assert setup.deferred_names == frozenset({"mcp_calc"})
    assert setup.tool_search_tool is not None
    assert setup.tool_search_tool.name == "tool_search"
    assert setup.catalog_hash


def test_tool_search_returns_command_with_hash_scoped_promotion():
    '验证 tool、search、returns、command、with、hash、scoped、promotion 场景下的预期行为、边界条件与结果'
    catalog = DeferredToolCatalog((mcp_calc,))
    ts = build_tool_search_tool(catalog)
    out = ts.invoke({"type": "tool_call", "name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "tc1"})
    assert isinstance(out, Command)
    promoted = out.update["promoted"]
    assert promoted == {"catalog_hash": catalog.hash, "names": ["mcp_calc"]}
    msg = out.update["messages"][0]
    assert msg.tool_call_id == "tc1" and msg.name == "tool_search"
    assert "mcp_calc" in msg.content


def test_tool_search_promotes_every_selected_tool():
    '验证 tool、search、promotes、every、selected、tool 场景下的预期行为、边界条件与结果。\n\n``select:`` promotes all named tools -- the tool closure must not re-cap.\n\n    ``DeferredToolCatalog.search`` already caps the ranked modes internally, so\n    a second ``[:MAX_RESULTS]`` in the closure only truncates ``select:``. Its\n    sibling closure, ``skills/describe.py::describe_skill``, calls\n    ``catalog.search(name)`` with no slice. Without this test, dropping the cap\n    inside ``search`` alone would still leave ``select:`` capped here.\n    '

    def _t(name: str):
        '执行 _t 的明确职责，并返回与调用约定一致的结果'
        @as_tool(name)
        def _f(query: str) -> str:
            '执行 _f 的明确职责，并返回与调用约定一致的结果。\n\nA deferred tool.'
            return query

        return _f

    names = [f"mcp_t{i}" for i in range(6)]  # 6 > MAX_RESULTS
    catalog = DeferredToolCatalog(tuple(_t(n) for n in names))
    ts = build_tool_search_tool(catalog)

    out = ts.invoke({"type": "tool_call", "name": "tool_search", "args": {"query": "select:" + ",".join(names)}, "id": "tc3"})

    assert out.update["promoted"]["names"] == names


def test_tool_search_no_match_empty_names():
    '验证 tool、search、no、match、empty、names 场景下的预期行为、边界条件与结果'
    catalog = DeferredToolCatalog((mcp_calc,))
    ts = build_tool_search_tool(catalog)
    out = ts.invoke({"type": "tool_call", "name": "tool_search", "args": {"query": "select:nonexistent"}, "id": "tc2"})
    assert out.update["promoted"]["names"] == []
