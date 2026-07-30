"""本模块覆盖运行 事件 存储 分页的行为、边界与回归场景，确保既有契约稳定。"""

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.fixture
def base_store():
    """为存储准备隔离的测试依赖，并由夹具作用域管理其生命周期。"""
    return MemoryRunEventStore()


@pytest.mark.anyio
async def test_list_messages_by_run_default_returns_all(base_store):
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = base_store
    for i in range(7):
        await store.put(
            thread_id="t1",
            run_id="run-a",
            event_type="human_message" if i % 2 == 0 else "ai_message",
            category="message",
            content=f"msg-a-{i}",
        )
    for i in range(3):
        await store.put(
            thread_id="t1",
            run_id="run-b",
            event_type="human_message",
            category="message",
            content=f"msg-b-{i}",
        )
    await store.put(thread_id="t1", run_id="run-a", event_type="tool_call", category="trace", content="trace")

    msgs = await store.list_messages_by_run("t1", "run-a")
    assert len(msgs) == 7
    assert all(m["category"] == "message" for m in msgs)
    assert all(m["run_id"] == "run-a" for m in msgs)


@pytest.mark.anyio
async def test_list_messages_by_run_with_limit(base_store):
    """验证运行 限制在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = base_store
    for i in range(7):
        await store.put(
            thread_id="t1",
            run_id="run-a",
            event_type="human_message" if i % 2 == 0 else "ai_message",
            category="message",
            content=f"msg-a-{i}",
        )

    msgs = await store.list_messages_by_run("t1", "run-a", limit=3)
    assert len(msgs) == 3
    seqs = [m["seq"] for m in msgs]
    assert seqs == sorted(seqs)


@pytest.mark.anyio
async def test_list_messages_by_run_after_seq(base_store):
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = base_store
    for i in range(7):
        await store.put(
            thread_id="t1",
            run_id="run-a",
            event_type="human_message" if i % 2 == 0 else "ai_message",
            category="message",
            content=f"msg-a-{i}",
        )

    all_msgs = await store.list_messages_by_run("t1", "run-a")
    cursor_seq = all_msgs[2]["seq"]
    msgs = await store.list_messages_by_run("t1", "run-a", after_seq=cursor_seq, limit=50)
    assert all(m["seq"] > cursor_seq for m in msgs)
    assert len(msgs) == 4


@pytest.mark.anyio
async def test_list_messages_by_run_before_seq(base_store):
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = base_store
    for i in range(7):
        await store.put(
            thread_id="t1",
            run_id="run-a",
            event_type="human_message" if i % 2 == 0 else "ai_message",
            category="message",
            content=f"msg-a-{i}",
        )

    all_msgs = await store.list_messages_by_run("t1", "run-a")
    cursor_seq = all_msgs[4]["seq"]
    msgs = await store.list_messages_by_run("t1", "run-a", before_seq=cursor_seq, limit=50)
    assert all(m["seq"] < cursor_seq for m in msgs)
    assert len(msgs) == 4


@pytest.mark.anyio
async def test_list_messages_by_run_does_not_include_other_run(base_store):
    """验证运行 运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = base_store
    for i in range(7):
        await store.put(
            thread_id="t1",
            run_id="run-a",
            event_type="human_message",
            category="message",
            content=f"msg-a-{i}",
        )
    for i in range(3):
        await store.put(
            thread_id="t1",
            run_id="run-b",
            event_type="human_message",
            category="message",
            content=f"msg-b-{i}",
        )

    msgs = await store.list_messages_by_run("t1", "run-b")
    assert len(msgs) == 3
    assert all(m["run_id"] == "run-b" for m in msgs)


@pytest.mark.anyio
async def test_list_messages_by_run_empty_run(base_store):
    """验证运行 运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = base_store
    msgs = await store.list_messages_by_run("t1", "nonexistent")
    assert msgs == []
