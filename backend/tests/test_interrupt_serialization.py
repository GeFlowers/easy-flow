"""覆盖本文件的鉴权或中断序列化回归边界。"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import StateGraph
from langgraph.types import Interrupt, interrupt


def _interrupting_node(state: dict) -> dict[str, Any]:
    """构造最小测试前置条件，隔离外部依赖并保持断言可重复。"""
    result = interrupt("Please provide API credentials")
    return {"result": result}


def _build_test_graph():
    """构造最小测试前置条件，隔离外部依赖并保持断言可重复。"""
    builder = StateGraph(dict)
    builder.add_node("ask_credential", _interrupting_node)
    builder.set_entry_point("ask_credential")
    builder.set_finish_point("ask_credential")
    return builder.compile()


class _StreamCollector:
    """提供受控事件收集替身，验证中断载荷的生命周期。"""
    def __init__(self):
        """构造最小测试前置条件，隔离外部依赖并保持断言可重复。"""
        self.events: list[tuple[str, Any]] = []

    async def publish(self, _run_id: str, event: str, data: Any):
        """构造最小测试前置条件，隔离外部依赖并保持断言可重复。"""
        self.events.append((event, data))


@pytest.mark.asyncio
async def test_values_mode_includes_interrupt():
    """验证既有契约在返回结构、异常传播或资源隔离变化时明确失败。"""
    from deerflow.runtime.serialization import serialize

    graph = _build_test_graph()
    collector = _StreamCollector()
    async for chunk in graph.astream({"messages": []}, stream_mode="values"):
        data = serialize(chunk, mode="values")
        await collector.publish("test", "values", data)
    interrupt_events = [e for e in collector.events if isinstance(e[1], dict) and "__interrupt__" in e[1]]
    assert len(interrupt_events) > 0, "__interrupt__ was stripped from values events"
    # 此处固定序列化或鉴权边界，避免回归退化为不可验证状态。
    interrupt_value = interrupt_events[0][1]["__interrupt__"]
    assert isinstance(interrupt_value, list)
    assert len(interrupt_value) > 0
    assert isinstance(interrupt_value[0], dict)
    assert interrupt_value[0]["value"] == "Please provide API credentials"


@pytest.mark.asyncio
async def test_serialize_channel_values_keeps_interrupt():
    """验证既有契约在返回结构、异常传播或资源隔离变化时明确失败。"""
    from deerflow.runtime.serialization import serialize_channel_values

    interrupt_obj = Interrupt(value={"question": "Enter API key"}, id="test-interrupt-id")
    result = serialize_channel_values(
        {
            "__interrupt__": (interrupt_obj,),
            "__pregel_tasks": "internal",
            "messages": [],
        }
    )
    assert "__interrupt__" in result
    assert "__pregel_tasks" not in result
    assert "messages" in result
    # 此处固定序列化或鉴权边界，避免回归退化为不可验证状态。
    assert isinstance(result["__interrupt__"], list)
    assert len(result["__interrupt__"]) > 0
    assert isinstance(result["__interrupt__"][0], dict)
    assert result["__interrupt__"][0]["value"] == {"question": "Enter API key"}
