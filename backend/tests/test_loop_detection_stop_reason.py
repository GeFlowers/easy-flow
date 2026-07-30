"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from deerflow.runtime import RunContext, RunManager, RunStatus
from deerflow.runtime.runs.worker import run_agent


@pytest.mark.asyncio
async def test_worker_surfaces_stop_reason_from_loop_detection():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

    run_manager = RunManager()
    record = await run_manager.create("thread-1")

    mw = LoopDetectionMiddleware(warn_threshold=1, hard_limit=3, window_size=5)
    captured_runtime: list[Any] = [None]

    class DummyAgent:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        metadata: dict[str, Any] = {"model_name": "test-model"}

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            runtime = ((config or {}).get("configurable") or {}).get("__pregel_runtime")
            assert runtime is not None, "LangGraph Runtime must be in configurable"
            captured_runtime[0] = runtime

            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            tool_calls = [{"name": "bash", "args": {"command": "ls"}, "id": "c1", "type": "tool_call"}]
            for _ in range(2):
                mw._apply({"messages": [AIMessage(content="", tool_calls=tool_calls)]}, runtime)
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            mw._apply({"messages": [AIMessage(content="", tool_calls=tool_calls)]}, runtime)

            yield {"messages": [AIMessage(content="Done.")]}

    bridge = AsyncMock()
    bridge.publish = AsyncMock()
    bridge.publish_end = AsyncMock()
    bridge.cleanup = AsyncMock()

    def factory(*, config):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=factory,
        graph_input={"messages": []},
        config={},
    )

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured_runtime[0] is not None, "DummyAgent never captured runtime"
    runtime_ctx = captured_runtime[0].context
    assert isinstance(runtime_ctx, dict)
    assert runtime_ctx.get("stop_reason") == "loop_capped", "The runtime the DummyAgent wrote to is the same one the worker read from"

    fetched = await run_manager.get(record.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.success
    assert fetched.stop_reason == "loop_capped"


@pytest.mark.asyncio
async def test_worker_surfaces_stop_reason_from_token_budget():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
    from deerflow.config.token_budget_config import TokenBudgetConfig

    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    config = TokenBudgetConfig(
        enabled=True,
        max_tokens=1000,
        hard_stop_threshold=0.0,
        warn_threshold=0.0,
    )
    mw = TokenBudgetMiddleware(config=config)
    captured_runtime: list[Any] = [None]

    class DummyAgent:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        metadata: dict[str, Any] = {"model_name": "test-model"}

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            runtime = ((config or {}).get("configurable") or {}).get("__pregel_runtime")
            assert runtime is not None, "LangGraph Runtime must be in configurable"
            captured_runtime[0] = runtime

            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            msg = AIMessage(
                id="msg-budget",
                content="hello",
                usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            )
            mw._apply({"messages": [msg]}, runtime)

            yield {"messages": [AIMessage(content="Budget exceeded, wrapping up.")]}

    bridge = AsyncMock()
    bridge.publish = AsyncMock()
    bridge.publish_end = AsyncMock()
    bridge.cleanup = AsyncMock()

    def factory(*, config):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=factory,
        graph_input={"messages": []},
        config={},
    )
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert captured_runtime[0] is not None, "DummyAgent never captured runtime"
    runtime_ctx = captured_runtime[0].context
    assert isinstance(runtime_ctx, dict)
    assert runtime_ctx.get("stop_reason") == "token_capped"

    fetched = await run_manager.get(record.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.success
    assert fetched.stop_reason == "token_capped"


@pytest.mark.asyncio
async def test_worker_surfaces_stop_reason_from_safety_finish_reason():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from unittest.mock import MagicMock

    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from deerflow.agents.middlewares.safety_termination_detectors import SafetyTermination

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    always_detector = MagicMock()
    always_detector.name = "test-always-fire"
    always_detector.detect.return_value = SafetyTermination(
        detector="test-always-fire",
        reason_field="finish_reason",
        reason_value="content_filter",
    )
    mw = SafetyFinishReasonMiddleware(detectors=[always_detector])
    captured_runtime: list[Any] = [None]

    class DummyAgent:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        metadata: dict[str, Any] = {"model_name": "test-model"}

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            runtime = ((config or {}).get("configurable") or {}).get("__pregel_runtime")
            assert runtime is not None
            captured_runtime[0] = runtime

            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            msg = AIMessage(
                content="I can't do that.",
                tool_calls=[{"name": "bash", "args": {}, "id": "c1", "type": "tool_call"}],
                response_metadata={"finish_reason": "content_filter"},
            )
            mw._apply({"messages": [msg]}, runtime)

            yield {"messages": [AIMessage(content="Safety filter triggered.")]}

    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = AsyncMock()
    bridge.publish = AsyncMock()
    bridge.publish_end = AsyncMock()
    bridge.cleanup = AsyncMock()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={"messages": []},
        config={},
    )

    assert captured_runtime[0] is not None
    assert captured_runtime[0].context.get("stop_reason") == "safety_capped"

    fetched = await run_manager.get(record.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.success
    assert fetched.stop_reason == "safety_capped"


@pytest.mark.asyncio
async def test_worker_surfaces_stop_reason_from_subagent_limit():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    mw = SubagentLimitMiddleware(max_concurrent=3, max_total=1)
    captured_runtime: list[Any] = [None]

    class DummyAgent:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
        metadata: dict[str, Any] = {"model_name": "test-model"}

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            runtime = ((config or {}).get("configurable") or {}).get("__pregel_runtime")
            assert runtime is not None
            captured_runtime[0] = runtime

            run_id = runtime.context.get("run_id")
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            state: dict[str, Any] = {
                "messages": [
                    AIMessage(
                        content="Delegating...",
                        tool_calls=[{"name": "task", "args": {"subagent_type": "general-purpose"}, "id": "c1", "type": "tool_call"}],
                    )
                ],
                "delegations": [{"id": "prior-delegation", "run_id": run_id}],
            }
            mw._truncate_task_calls(state, runtime)

            yield {"messages": [AIMessage(content="Subagent limit reached.")]}

    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = AsyncMock()
    bridge.publish = AsyncMock()
    bridge.publish_end = AsyncMock()
    bridge.cleanup = AsyncMock()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={"messages": []},
        config={},
    )

    assert captured_runtime[0] is not None
    assert captured_runtime[0].context.get("stop_reason") == "subagent_limit_capped"

    fetched = await run_manager.get(record.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.success
    assert fetched.stop_reason == "subagent_limit_capped"
