'未说明'

import asyncio

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.builtins.tool_search import assemble_deferred_tools, get_deferred_tools_prompt_section
from deerflow.tools.mcp_metadata import tag_mcp_tool


@as_tool
def active_tool(x: str) -> str:
    """处理工具相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
    return x


@as_tool
def mcp_calc(expression: str) -> str:
    '未说明'
    return expression


@as_tool
def mcp_other(x: str) -> str:
    '未说明'
    return x


def test_subagent_deferral_recipe_hides_then_promotes():
    '未说明'
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        '未说明'
        def bind_tools(self, tools, **kwargs):
            '未说明'
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    # The subagent build path (executor._build_initial_state): policy-filtered
    # tools -> assemble_deferred_tools appends tool_search, fail-closed.
    filtered = [active_tool, tag_mcp_tool(mcp_calc), tag_mcp_tool(mcp_other)]
    final_tools, setup = assemble_deferred_tools(filtered, enabled=True)
    assert "tool_search" in [t.name for t in final_tools]
    assert setup.deferred_names == frozenset({"mcp_calc", "mcp_other"})

    # The subagent injects the section into its single SystemMessage.
    section = get_deferred_tools_prompt_section(deferred_names=setup.deferred_names)
    assert "<available-deferred-tools>" in section
    assert "mcp_calc" in section and "mcp_other" in section

    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))

    # The middleware DeferredToolFilterMiddleware is exactly what
    # build_subagent_runtime_middlewares attaches for this setup (locked by
    # tests/test_tool_error_handling_middleware.py); the subagent build passes
    # system_prompt=None with state_schema=ThreadState.
    graph = create_agent(
        model=model,
        tools=final_tools,
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        system_prompt=None,
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [SystemMessage(content=section), HumanMessage(content="use the deferred calculator")]}))

    assert len(bound) >= 2, f"expected >=2 model binds, got {bound}"
    # Turn 1: both deferred MCP tools hidden from the subagent's model binding.
    assert "mcp_calc" not in bound[0] and "mcp_other" not in bound[0]
    # Turn 2: the searched tool is promoted; the un-searched one stays hidden.
    assert "mcp_calc" in bound[1]
    assert "mcp_other" not in bound[1]
    # Promotion recorded in graph state, scoped by catalog hash.
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["mcp_calc"]}


def test_subagent_builder_emits_working_deferred_filter():
    '未说明'
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from deerflow.config.app_config import AppConfig, CircuitBreakerConfig
    from deerflow.config.guardrails_config import GuardrailsConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        '未说明'
        def bind_tools(self, tools, **kwargs):
            '未说明'
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    filtered = [active_tool, tag_mcp_tool(mcp_calc), tag_mcp_tool(mcp_other)]
    final_tools, setup = assemble_deferred_tools(filtered, enabled=True)
    section = get_deferred_tools_prompt_section(deferred_names=setup.deferred_names)

    app_config = AppConfig(
        models=[
            ModelConfig(
                name="test-model",
                display_name="test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="test-model",
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="test"),
        guardrails=GuardrailsConfig(enabled=False),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=7, recovery_timeout_sec=11),
    )

    # The exact call executor._create_agent makes. Pull the filter the builder
    # produced (not a hand-rolled one) so its wiring - deferred set + catalog hash -
    # is what's under test.
    middlewares = build_subagent_runtime_middlewares(app_config=app_config, model_name="test-model", deferred_setup=setup)
    deferred_filters = [m for m in middlewares if isinstance(m, DeferredToolFilterMiddleware)]
    assert len(deferred_filters) == 1, f"builder must emit exactly one deferred filter, got {[type(m).__name__ for m in middlewares]}"

    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))

    # Run only the builder-produced filter (the component under test). The other
    # runtime middlewares need sandbox/thread infra to *execute*, so running the
    # full stack here would be flaky; their attachment + ordering before Safety is
    # locked in tests/test_tool_error_handling_middleware.py.
    graph = create_agent(
        model=model,
        tools=final_tools,
        middleware=deferred_filters,
        system_prompt=None,
        state_schema=ThreadState,
    )
    result = asyncio.run(graph.ainvoke({"messages": [SystemMessage(content=section), HumanMessage(content="use the deferred calculator")]}))

    assert len(bound) >= 2, f"expected >=2 model binds, got {bound}"
    # Turn 1: both deferred MCP tools hidden - the builder-produced filter is active.
    assert "mcp_calc" not in bound[0] and "mcp_other" not in bound[0]
    # Turn 2: the searched tool is promoted - proves the builder wired the catalog
    # hash correctly (a wrong hash would leave mcp_calc hidden here).
    assert "mcp_calc" in bound[1]
    assert "mcp_other" not in bound[1]
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["mcp_calc"]}
