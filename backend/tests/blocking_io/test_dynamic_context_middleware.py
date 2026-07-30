"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from types import SimpleNamespace
from unittest import mock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.dynamic_context_middleware import (
    _DYNAMIC_CONTEXT_REMINDER_KEY,
    DynamicContextMiddleware,
)
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY

pytestmark = pytest.mark.asyncio


class _FakeModel(FakeMessagesListChatModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return self


async def test_abefore_agent_does_not_block_event_loop() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mw = DynamicContextMiddleware()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    original_build = mw._build_full_reminder

    def slow_build_reminder():
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        import time

        time.sleep(0.05)  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        return original_build()

    with (
        mock.patch.object(mw, "_build_full_reminder", slow_build_reminder),
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""),
    ):
        agent = await asyncio.to_thread(
            lambda: create_agent(
                model=_FakeModel(responses=[AIMessage(content="ok")]),
                tools=[],
                middleware=[mw],
            )
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            {"configurable": {"thread_id": "test-thread"}},
        )

    assert result["messages"]


async def test_abefore_agent_returns_same_result_as_before_agent() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mw = DynamicContextMiddleware()

    state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
    runtime = SimpleNamespace(context={})

    with (
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-05, Friday"

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        sync_result = mw.before_agent(state, runtime)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        async_result = await mw.abefore_agent(state, runtime)

    assert sync_result is not None
    assert async_result is not None
    assert sync_result.keys() == async_result.keys()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(sync_result["messages"]) == 2
    assert len(async_result["messages"]) == 2
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sync_result["messages"][0].id == async_result["messages"][0].id
    assert sync_result["messages"][1].id == async_result["messages"][1].id


async def test_abefore_agent_returns_none_on_timeout() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mw = DynamicContextMiddleware()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    journal = mock.MagicMock()

    def blocking_inject(state):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        started.set()
        release.wait(timeout=2)
        try:
            return {
                "messages": [
                    HumanMessage(
                        content="<memory>late context</memory>",
                        id="msg-1__memory",
                        additional_kwargs={
                            _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                        },
                    )
                ]
            }
        finally:
            finished.set()

    with (
        mock.patch.object(mw, "_inject", blocking_inject),
        mock.patch(
            "deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS",
            0.01,
        ),
    ):
        state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
        runtime = SimpleNamespace(context={"__run_journal": journal})
        result = await mw.abefore_agent(state, runtime)

    assert started.is_set()
    assert result is None
    release.set()
    assert await asyncio.to_thread(finished.wait, 1)
    journal.record_memory_context.assert_not_called()


async def test_abefore_agent_records_checkpointed_memory_on_timeout() -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    mw = DynamicContextMiddleware()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    journal = mock.MagicMock()
    memory_content = "<memory>checkpoint context</memory>"

    def blocking_inject(state):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        started.set()
        release.wait(timeout=2)
        try:
            return {
                "messages": [
                    HumanMessage(
                        content="<memory>late replacement</memory>",
                        id="msg-2__memory",
                        additional_kwargs={_DYNAMIC_CONTEXT_REMINDER_KEY: True},
                    )
                ]
            }
        finally:
            finished.set()

    state = {
        "messages": [
            HumanMessage(
                content=memory_content,
                id="msg-1__memory",
                additional_kwargs={_DYNAMIC_CONTEXT_REMINDER_KEY: True},
            )
        ]
    }
    runtime = SimpleNamespace(
        context={
            "__run_journal": journal,
            CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"msg-1__memory"}),
        }
    )

    with (
        mock.patch.object(mw, "_inject", blocking_inject),
        mock.patch(
            "deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS",
            0.01,
        ),
    ):
        result = await mw.abefore_agent(state, runtime)

    recorded_call = journal.record_memory_context.call_args
    release.set()
    assert await asyncio.to_thread(finished.wait, 1)
    assert started.is_set()
    assert result is None
    assert recorded_call == mock.call(
        content_sha256=hashlib.sha256(memory_content.encode("utf-8")).hexdigest(),
    )
    journal.record_memory_context.assert_called_once()
