'定义 test_deferred_filter_middleware 模块提供的职责与可复用接口。\n\nTests for DeferredToolFilterMiddleware (closure deferred-set + state promotion).'

from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware


@as_tool
def mcp_a(x: str) -> str:
    '执行 mcp_a 的明确职责，并返回与调用约定一致的结果。\n\na'
    return x


@as_tool
def mcp_b(x: str) -> str:
    '执行 mcp_b 的明确职责，并返回与调用约定一致的结果。\n\nb'
    return x


@as_tool
def active_c(x: str) -> str:
    '执行 active_c 的明确职责，并返回与调用约定一致的结果。\n\nc'
    return x


class _Req:
    '封装 _Req 的状态、协作关系与公开操作'
    def __init__(self, tools, state):
        '实现 __init__ 协议方法，保持对象交互语义一致'
        self.tools = tools
        self.state = state
        self.overridden = None

    def override(self, tools):
        '执行 override 的明确职责，并返回与调用约定一致的结果'
        self.overridden = tools
        return self


def _mw():
    '执行 _mw 的明确职责，并返回与调用约定一致的结果'
    return DeferredToolFilterMiddleware(frozenset({"mcp_a", "mcp_b"}), "h1")


def test_hides_all_deferred_when_no_promotion():
    '验证 hides、all、deferred、when、no、promotion 场景下的预期行为、边界条件与结果'
    req = _Req([mcp_a, mcp_b, active_c], {})
    out = _mw()._filter_tools(req)
    assert [t.name for t in out.overridden] == ["active_c"]


def test_promoted_under_matching_hash_passes_through():
    '验证 promoted、under、matching、hash、passes、through 场景下的预期行为、边界条件与结果'
    req = _Req([mcp_a, mcp_b, active_c], {"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})
    out = _mw()._filter_tools(req)
    assert {t.name for t in out.overridden} == {"mcp_a", "active_c"}


def test_promotion_ignored_when_hash_mismatch():
    '验证 promotion、ignored、when、hash、mismatch 场景下的预期行为、边界条件与结果'
    req = _Req([mcp_a, mcp_b, active_c], {"promoted": {"catalog_hash": "STALE", "names": ["mcp_a"]}})
    out = _mw()._filter_tools(req)
    assert [t.name for t in out.overridden] == ["active_c"]


def test_no_deferred_names_is_noop():
    '验证 no、deferred、names、is、noop 场景下的预期行为、边界条件与结果'
    req = _Req([active_c], {})
    out = DeferredToolFilterMiddleware(frozenset(), "h1")._filter_tools(req)
    assert out.overridden is None  # returned unchanged


def test_blocked_message_for_unpromoted_deferred_call():
    '验证 blocked、message、for、unpromoted、deferred、call 场景下的预期行为、边界条件与结果'
    class _TCReq:
        '封装 _TCReq 的状态、协作关系与公开操作'
        tool_call = {"name": "mcp_a", "id": "tc1"}
        state = {}

    msg = _mw()._blocked_tool_message(_TCReq())
    assert msg is not None and msg.status == "error" and "tool_search" in msg.content


def test_no_block_for_promoted_call():
    '验证 no、block、for、promoted、call 场景下的预期行为、边界条件与结果'
    class _TCReq:
        '封装 _TCReq 的状态、协作关系与公开操作'
        tool_call = {"name": "mcp_a", "id": "tc1"}
        state = {"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}}

    assert _mw()._blocked_tool_message(_TCReq()) is None


def test_no_block_for_non_deferred_call():
    '验证 no、block、for、non、deferred、call 场景下的预期行为、边界条件与结果'
    class _TCReq:
        '封装 _TCReq 的状态、协作关系与公开操作'
        tool_call = {"name": "active_c", "id": "tc1"}
        state = {}

    assert _mw()._blocked_tool_message(_TCReq()) is None
