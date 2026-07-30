"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from typing import Any
from unittest import mock

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.dynamic_context_middleware import (
    DynamicContextMiddleware,
    is_dynamic_context_reminder,
)

_TURN_1 = "test"
_TURN_2 = "tell me the weather of next week in berlin"
_FIXED_DATE = "2026-05-08, Friday"
_MEMORY = "<memory>\nUser prefers concise answers.\n</memory>"


class _FakeModel(FakeMessagesListChatModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Runnable:  # type: ignore[override]
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return self


class _RecordModelInput(AgentMiddleware):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def __init__(self) -> None:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        super().__init__()
        self.calls: list[list[Any]] = []

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.calls.append(list(request.messages))
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        self.calls.append(list(request.messages))
        return await handler(request)


def _msg_text(msg: Any) -> str:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    content = msg.content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _last_human_text(messages: list[Any]) -> str:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
            continue
        if msg.additional_kwargs.get("hide_from_ui") or is_dynamic_context_reminder(msg):
            continue
        return _msg_text(msg)
    return ""


def _assert_stream_well_formed(messages: list[Any], *, newest_user_text: str) -> None:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert _last_human_text(messages) == newest_user_text, "newest user message is not the latest human turn (stranded / stale re-answer)"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    occurrences = sum(1 for m in messages if isinstance(m, HumanMessage) and _msg_text(m) == newest_user_text)
    assert occurrences == 1, f"newest user message appears {occurrences} times, expected 1"

    ids = [m.id for m in messages if m.id is not None]
    assert len(ids) == len(set(ids)), f"duplicate message ids in stream: {ids}"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert not any("__user__user" in (mid or "") for mid in ids), f"id-suffix explosion (re-injection): {ids}"


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
_STREAM_MIDDLEWARES: tuple[type[AgentMiddleware], ...] = (DynamicContextMiddleware,)


def _run_two_turns() -> tuple[dict, _RecordModelInput]:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    recorder = _RecordModelInput()
    agent = create_agent(
        model=_FakeModel(responses=[AIMessage(content="ack-1"), AIMessage(content="ack-2")]),
        tools=[],
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        middleware=[recorder, *(make() for make in _STREAM_MIDDLEWARES)],
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "stream-invariants-1"}}

    with (
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=_MEMORY),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = _FIXED_DATE
        agent.invoke({"messages": [HumanMessage(content=_TURN_1, id="u1")]}, cfg)
        final = agent.invoke({"messages": [HumanMessage(content=_TURN_2, id="u2")]}, cfg)

    return final, recorder


def test_second_turn_model_receives_newest_user_message():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    _final, recorder = _run_two_turns()

    assert len(recorder.calls) >= 2, f"expected a model call per turn, got {len(recorder.calls)}"
    turn_2_request = recorder.calls[-1]
    _assert_stream_well_formed(turn_2_request, newest_user_text=_TURN_2)


def test_second_turn_persisted_state_is_well_formed():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    final, _recorder = _run_two_turns()
    _assert_stream_well_formed(final["messages"], newest_user_text=_TURN_2)
