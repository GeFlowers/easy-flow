"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.asyncio


class _FakeModel(FakeMessagesListChatModel):
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return self


async def test_before_agent_uploads_scan_does_not_block_event_loop(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from langchain.agents import create_agent

    from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
    from deerflow.runtime.user_context import get_effective_user_id

    mw = await asyncio.to_thread(UploadsMiddleware, str(tmp_path))
    uploads_dir = await asyncio.to_thread(mw._paths.sandbox_uploads_dir, "t1", user_id=get_effective_user_id())
    uploads_dir.mkdir(parents=True, exist_ok=True)  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    (uploads_dir / "existing.txt").write_text("hello", encoding="utf-8")

    agent = await asyncio.to_thread(lambda: create_agent(model=_FakeModel(responses=[AIMessage(content="ok")]), tools=[], middleware=[mw]))

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        {"configurable": {"thread_id": "t1"}},
    )

    assert result["messages"]
