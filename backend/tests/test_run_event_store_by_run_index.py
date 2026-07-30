"""本模块覆盖运行 事件 存储 运行的行为、边界与回归场景，确保既有契约稳定。"""

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


def _ref_messages_by_run(records, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None):
    """准备可控测试资源与状态，供后续断言读取。"""
    filtered = [e for e in records if e["thread_id"] == thread_id and e["run_id"] == run_id and e["category"] == "message"]
    if before_seq is not None:
        filtered = [e for e in filtered if e["seq"] < before_seq]
    if after_seq is not None:
        filtered = [e for e in filtered if e["seq"] > after_seq]
    if after_seq is not None:
        return filtered[:limit]
    return filtered[-limit:] if len(filtered) > limit else filtered


def _ref_events(records, thread_id, run_id, *, event_types=None, limit=500):
    """准备可控测试资源与状态，供后续断言读取。"""
    filtered = [e for e in records if e["thread_id"] == thread_id and e["run_id"] == run_id]
    if event_types is not None:
        filtered = [e for e in filtered if e["event_type"] in event_types]
    return filtered[:limit]


async def _seed(store):
    """准备可控测试资源与状态，供后续断言读取。"""
    plan = [
        ("run-a", "message"),
        ("run-a", "trace"),
        ("run-b", "message"),
        ("run-a", "message"),
        ("run-b", "trace"),
        ("run-b", "message"),
        ("run-a", "trace"),
        ("run-a", "message"),
        ("run-b", "message"),
        ("run-a", "message"),
        ("run-b", "message"),
        ("run-a", "message"),
    ]
    records = []
    for i, (run_id, category) in enumerate(plan):
        rec = await store.put(thread_id="t1", run_id=run_id, event_type=f"e{i}", category=category, content=str(i))
        records.append(rec)
    return records


@pytest.mark.anyio
async def test_list_messages_by_run_matches_reference_across_cursors():
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = MemoryRunEventStore()
    records = await _seed(store)
    seqs = [r["seq"] for r in records]
    cursors = [None, 0, *seqs, max(seqs) + 1]
    for run_id in ("run-a", "run-b", "run-missing"):
        for limit in (1, 2, 3, 50):
            for before_seq in cursors:
                for after_seq in cursors:
                    got = await store.list_messages_by_run("t1", run_id, limit=limit, before_seq=before_seq, after_seq=after_seq)
                    want = _ref_messages_by_run(records, "t1", run_id, limit=limit, before_seq=before_seq, after_seq=after_seq)
                    assert got == want, (run_id, limit, before_seq, after_seq)


@pytest.mark.anyio
async def test_list_events_matches_reference_with_filters():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    store = MemoryRunEventStore()
    records = await _seed(store)
    all_types = sorted({r["event_type"] for r in records})
    for run_id in ("run-a", "run-b", "run-missing"):
        assert await store.list_events("t1", run_id) == _ref_events(records, "t1", run_id)
        assert await store.list_events("t1", run_id, limit=2) == _ref_events(records, "t1", run_id, limit=2)
        for et in all_types:
            assert await store.list_events("t1", run_id, event_types=[et]) == _ref_events(records, "t1", run_id, event_types=[et])


@pytest.mark.anyio
async def test_run_keyed_index_partitions_every_event():
    """验证运行 事件在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = MemoryRunEventStore()
    records = await _seed(store)
    indexed = [e for run_events in store._events_by_run["t1"].values() for e in run_events]
    assert sorted(e["seq"] for e in indexed) == sorted(r["seq"] for r in records)
    for run_id, run_events in store._events_by_run["t1"].items():
        assert all(e["run_id"] == run_id for e in run_events)
        assert [e["seq"] for e in run_events] == sorted(e["seq"] for e in run_events)
    for run_id, run_msgs in store._messages_by_run["t1"].items():
        assert all(e["run_id"] == run_id and e["category"] == "message" for e in run_msgs)


@pytest.mark.anyio
async def test_run_index_stays_in_lockstep_after_delete_by_run():
    """验证运行 运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = MemoryRunEventStore()
    await _seed(store)
    removed = await store.delete_by_run("t1", "run-a")
    assert removed == 7  # run-a: 5 messages + 2 traces

    # The deleted run vanishes from both per-run reads.
    assert await store.list_events("t1", "run-a") == []
    assert await store.list_messages_by_run("t1", "run-a") == []
    assert "run-a" not in store._events_by_run.get("t1", {})
    assert "run-a" not in store._messages_by_run.get("t1", {})

    # The surviving run is untouched, and the thread-wide projection agrees.
    msgs_b = await store.list_messages_by_run("t1", "run-b")
    assert len(msgs_b) == 4
    assert all(m["run_id"] == "run-b" for m in msgs_b)
    assert all(m["run_id"] == "run-b" for m in await store.list_messages("t1"))


@pytest.mark.anyio
async def test_delete_by_thread_clears_run_indexes():
    """验证会话 运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = MemoryRunEventStore()
    await _seed(store)
    await store.delete_by_thread("t1")
    assert "t1" not in store._events_by_run
    assert "t1" not in store._messages_by_run
    assert await store.list_events("t1", "run-a") == []
    assert await store.list_messages_by_run("t1", "run-b") == []
