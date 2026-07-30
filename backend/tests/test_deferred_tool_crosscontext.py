"定义 test_deferred_tool_crosscontext 模块提供的职责与可复用接口。\n\nRegressions for the deferred-tool redesign (#3272).\n\n- Cross-context: building the graph in one async context and running it in a\n  sibling context (that did NOT inherit the build context) must still hide\n  deferred tools. The old ContextVar implementation failed this; the closure +\n  graph-state implementation must pass.\n- Policy leak (Finding 1): a tool removed by policy must not be searchable.\n- Fail-closed (Finding 2): a wiring regression must raise, not silently leak.\n- #2884 isolation: a second (subagent-style) setup build must not affect the\n  lead agent's middleware/promotion.\n"

import asyncio
from pathlib import Path

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.skills.tool_policy import filter_tools_by_skill_allowed_tools
from deerflow.skills.types import Skill
from deerflow.tools.builtins.tool_search import DeferredToolSetup, assemble_deferred_tools, build_deferred_tool_setup
from deerflow.tools.mcp_metadata import tag_mcp_tool


@as_tool
def active_tool(x: str) -> str:
    '执行 active_tool 的明确职责，并返回与调用约定一致的结果。\n\nactive'
    return x


@as_tool
def mcp_secret(x: str) -> str:
    '执行 mcp_secret 的明确职责，并返回与调用约定一致的结果。\n\ndeferred mcp tool — must be hidden from bind_tools until promoted'
    return x


_BOUND: list[list[str]] = []


class _RecordingModel(GenericFakeChatModel):
    '封装 _RecordingModel 的状态、协作关系与公开操作'
    def bind_tools(self, tools, **kwargs):
        '执行 bind_tools 的明确职责，并返回与调用约定一致的结果'
        _BOUND.append([getattr(t, "name", None) for t in tools])
        return self


def _build_graph():
    '执行 _build_graph 的明确职责，并返回与调用约定一致的结果'
    filtered = [active_tool, tag_mcp_tool(mcp_secret)]
    setup = build_deferred_tool_setup(filtered, enabled=True)
    final = [*filtered, setup.tool_search_tool]
    model = _RecordingModel(messages=iter([AIMessage(content="done")] * 4))
    return create_agent(
        model=model,
        tools=final,
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        system_prompt="t",
    )


async def _abuild():
    '执行 _abuild 的明确职责，并返回与调用约定一致的结果'
    return _build_graph()


def test_deferred_hidden_when_built_and_run_in_different_contexts():
    '验证 deferred、hidden、when、built、and、run、in、different、contexts 场景下的预期行为、边界条件与结果。\n\nBuild in one task, run in a sibling task that did not inherit it.'
    _BOUND.clear()

    async def main():
        '执行 main 的明确职责，并返回与调用约定一致的结果'
        graph = await asyncio.create_task(_abuild())

        async def run():
            '执行任务并返回执行结果，并遵守 run 所表达的接口约束'
            await graph.ainvoke({"messages": [HumanMessage(content="hi")]})

        await asyncio.create_task(run())

    asyncio.run(main())

    assert _BOUND, "model was never bound"
    assert not any("mcp_secret" in names for names in _BOUND), f"deferred MCP tool leaked into bind_tools: {_BOUND}"


def test_policy_excluded_mcp_tool_not_in_catalog():
    '验证 policy、excluded、mcp、tool、not、in、catalog 场景下的预期行为、边界条件与结果。\n\nFinding 1: a tool removed by policy is not searchable/exposed.'
    filtered_after_policy = [active_tool]  # mcp_secret denied by skill allowed-tools
    setup = build_deferred_tool_setup(filtered_after_policy, enabled=True)
    assert setup.deferred_names == frozenset()
    assert setup.tool_search_tool is None


def test_fail_closed_when_mcp_survives_without_setup(monkeypatch):
    '验证 fail、closed、when、mcp、survives、without、setup 场景下的预期行为、边界条件与结果。\n\nFinding 2: simulate a wiring regression and assert it fails loudly.\n\n    ``assemble_deferred_tools`` references ``build_deferred_tool_setup`` as a\n    module global, so patch it in ``tool_search`` (its home module).\n    '
    monkeypatch.setattr(
        "deerflow.tools.builtins.tool_search.build_deferred_tool_setup",
        lambda tools, *, enabled: DeferredToolSetup(None, frozenset(), None),
    )
    with pytest.raises(RuntimeError, match="fail-closed"):
        assemble_deferred_tools([tag_mcp_tool(mcp_secret)], enabled=True)


def test_subagent_reentry_does_not_touch_lead_state():
    "验证 subagent、reentry、does、not、touch、lead、state 场景下的预期行为、边界条件与结果。\n\n#2884: building a second (subagent) setup must not affect the lead's\n    middleware. With no shared registry/ContextVar, the lead middleware depends\n    only on its own deferred_names + the passed state."
    lead_setup = build_deferred_tool_setup([active_tool, tag_mcp_tool(mcp_secret)], enabled=True)
    mw = DeferredToolFilterMiddleware(lead_setup.deferred_names, lead_setup.catalog_hash)

    # Simulate a subagent build re-entering tool assembly with its own setup.
    _ = build_deferred_tool_setup([tag_mcp_tool(mcp_secret)], enabled=True)

    class _Req:
        '封装 _Req 的状态、协作关系与公开操作'
        def __init__(self):
            '实现 __init__ 协议方法，保持对象交互语义一致'
            self.tools = [active_tool, mcp_secret]
            self.state = {"promoted": {"catalog_hash": lead_setup.catalog_hash, "names": ["mcp_secret"]}}

        def override(self, tools):
            '执行 override 的明确职责，并返回与调用约定一致的结果'
            self.tools = tools
            return self

    out = mw._filter_tools(_Req())
    assert {t.name for t in out.tools} == {"active_tool", "mcp_secret"}  # promotion intact


def _make_skill(allowed_tools):
    '执行 _make_skill 的明确职责，并返回与调用约定一致的结果。\n\nSkill carrying an explicit allowed-tools allowlist (None = legacy allow-all).'
    return Skill(
        name="s",
        description="d",
        license="MIT",
        skill_dir=Path("/tmp/s"),
        skill_file=Path("/tmp/s/SKILL.md"),
        relative_path=Path("s"),
        category="public",
        allowed_tools=tuple(allowed_tools) if allowed_tools is not None else None,
        enabled=True,
    )


def test_policy_denied_mcp_yields_no_tool_search_end_to_end():
    '验证 policy、denied、mcp、yields、no、tool、search、end、to、end 场景下的预期行为、边界条件与结果。\n\nAn allowlist that denies the MCP tool gates it end-to-end: after the real\n    policy filter no MCP tool survives, so ``assemble_deferred_tools`` adds no\n    tool_search (and does not fail-closed, because no MCP tool leaked through).'
    filtered = filter_tools_by_skill_allowed_tools([active_tool, tag_mcp_tool(mcp_secret)], [_make_skill(["active_tool"])])
    final_tools, setup = assemble_deferred_tools(filtered, enabled=True)

    assert [t.name for t in final_tools] == ["active_tool"]
    assert "tool_search" not in {t.name for t in final_tools}
    assert setup.deferred_names == frozenset()


def test_tool_search_appended_after_policy_but_never_exposes_denied_tool():
    '验证 tool、search、appended、after、policy、but、never、exposes、denied、tool 场景下的预期行为、边界条件与结果。\n\nIntentional behavior change vs. upstream (Copilot review on PR #3342).\n\n    ``tool_search`` is appended AFTER skill-allowlist filtering, so an allowlist\n    can no longer deny ``tool_search`` by name. This is safe by construction: the\n    tool only appears when allowed MCP tools survive the filter, and its catalog\n    is derived from the already policy-filtered list — so it can never expose a\n    tool the allowlist denied. Locks that contract so the ordering cannot regress.\n    '
    allowed = ["active_tool", "mcp_secret"]  # permits the MCP tool, does NOT list tool_search
    filtered = filter_tools_by_skill_allowed_tools([active_tool, tag_mcp_tool(mcp_secret)], [_make_skill(allowed)])
    final_tools, setup = assemble_deferred_tools(filtered, enabled=True)

    names = {t.name for t in final_tools}
    assert "tool_search" in names  # appended despite not being in the allowlist
    assert setup.deferred_names == frozenset({"mcp_secret"})
    assert set(setup.deferred_names) <= set(allowed)  # catalog never exceeds the allowlist
