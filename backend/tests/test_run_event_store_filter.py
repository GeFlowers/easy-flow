"""本模块覆盖运行 事件 存储的行为、边界与回归场景，确保既有契约稳定。"""

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


async def _seed_two_tasks(store):
    """准备可控测试资源与状态，供后续断言读取。"""
    await store.put(thread_id="t1", run_id="r1", event_type="subagent.start", category="subagent", content={"task_id": "A"}, metadata={"task_id": "A"})
    await store.put(thread_id="t1", run_id="r1", event_type="subagent.start", category="subagent", content={"task_id": "B"}, metadata={"task_id": "B"})
    for i in range(3):
        await store.put(thread_id="t1", run_id="r1", event_type="subagent.step", category="subagent", content={"task_id": "A", "message_index": i}, metadata={"task_id": "A", "message_index": i})
    for i in range(2):
        await store.put(thread_id="t1", run_id="r1", event_type="subagent.step", category="subagent", content={"task_id": "B", "message_index": i}, metadata={"task_id": "B", "message_index": i})


def _task_ids(events):
    """准备可控测试资源与状态，供后续断言读取。"""
    return [e["metadata"].get("task_id") for e in events]


async def _check_task_id_filter(store):
    """准备可控测试资源与状态，供后续断言读取。"""
    await _seed_two_tasks(store)
    a_events = await store.list_events("t1", "r1", task_id="A")
    assert _task_ids(a_events) == ["A", "A", "A", "A"]  # start + 3 steps
    b_events = await store.list_events("t1", "r1", task_id="B")
    assert _task_ids(b_events) == ["B", "B", "B"]  # start + 2 steps


async def _check_task_id_with_event_types(store):
    """准备可控测试资源与状态，供后续断言读取。"""
    await _seed_two_tasks(store)
    a_steps = await store.list_events("t1", "r1", task_id="A", event_types=["subagent.step"])
    assert [e["event_type"] for e in a_steps] == ["subagent.step"] * 3
    assert _task_ids(a_steps) == ["A", "A", "A"]


async def _check_after_seq_cursor(store):
    """准备可控测试资源与状态，供后续断言读取。"""
    await _seed_two_tasks(store)
    everything = await store.list_events("t1", "r1")
    cursor = everything[2]["seq"]
    after = await store.list_events("t1", "r1", after_seq=cursor)
    assert all(e["seq"] > cursor for e in after)
    assert len(after) == len(everything) - 3


async def _check_task_id_after_seq_paginate(store):
    """准备可控测试资源与状态，供后续断言读取。"""
    await _seed_two_tasks(store)
    collected = []
    after_seq = None
    for _ in range(10):  # safety bound
        page = await store.list_events("t1", "r1", task_id="A", event_types=["subagent.step"], limit=2, after_seq=after_seq)
        collected.extend(page)
        if len(page) < 2:
            break
        after_seq = page[-1]["seq"]
    assert [e["content"]["message_index"] for e in collected] == [0, 1, 2]


async def _check_no_task_id_returns_all(store):
    """准备可控测试资源与状态，供后续断言读取。"""
    await _seed_two_tasks(store)
    everything = await store.list_events("t1", "r1")
    assert len(everything) == 7  # 2 starts + 5 steps


# -- Memory backend --


@pytest.mark.anyio
async def test_memory_task_id_filter():
    """验证内存 任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    await _check_task_id_filter(MemoryRunEventStore())


@pytest.mark.anyio
async def test_memory_task_id_with_event_types():
    """验证内存 任务 事件在预期条件及边界场景下的可观察行为，防止相关回归。"""
    await _check_task_id_with_event_types(MemoryRunEventStore())


@pytest.mark.anyio
async def test_memory_after_seq_cursor():
    """验证内存在预期条件及边界场景下的可观察行为，防止相关回归。"""
    await _check_after_seq_cursor(MemoryRunEventStore())


@pytest.mark.anyio
async def test_memory_task_id_after_seq_paginate():
    """验证内存 任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    await _check_task_id_after_seq_paginate(MemoryRunEventStore())


@pytest.mark.anyio
async def test_memory_no_task_id_returns_all():
    """验证内存 任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    await _check_no_task_id_returns_all(MemoryRunEventStore())


# -- DB backend (sqlite): exercises the JSON-field filter on a real dialect --


@pytest.mark.anyio
async def test_db_task_id_filter(tmp_path):
    """验证任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        await _check_task_id_filter(DbRunEventStore(get_session_factory()))
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_db_task_id_after_seq_paginate(tmp_path):
    """验证任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        await _check_task_id_after_seq_paginate(DbRunEventStore(get_session_factory()))
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_db_no_task_id_returns_all(tmp_path):
    """验证任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        await _check_no_task_id_returns_all(DbRunEventStore(get_session_factory()))
    finally:
        await close_engine()


# -- JSONL backend --


@pytest.mark.anyio
async def test_jsonl_task_id_filter(tmp_path):
    """验证任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

    await _check_task_id_filter(JsonlRunEventStore(base_dir=str(tmp_path)))


@pytest.mark.anyio
async def test_jsonl_task_id_after_seq_paginate(tmp_path):
    """验证任务在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

    await _check_task_id_after_seq_paginate(JsonlRunEventStore(base_dir=str(tmp_path)))
