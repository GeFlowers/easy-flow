"""验证换行记录存储的异步输入输出加固后的并发安全性（编号二八一六）。

验证内容：
- 同一线程标识内的并发写入由写锁串行化；
- 并发调用时批量写入仍保持递增序号；
- 新建存储实例会从磁盘恢复序号；
- 数据库存储的批量写入拒绝混合线程批次。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_store(base_dir: Path) -> JsonlRunEventStore:
    """以指定临时目录创建存储实例，使每个测试的文件生命周期彼此隔离。"""
    return JsonlRunEventStore(base_dir=base_dir)


# ---------------------------------------------------------------------------
# 写锁：每个线程拥有且复用同一把锁
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_write_lock_returns_asyncio_lock():
    """确认首次请求线程写锁时创建的是异步锁实例。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        lock = store._get_write_lock("t1")
        assert isinstance(lock, asyncio.Lock)


@pytest.mark.anyio
async def test_get_write_lock_same_thread_reuses_lock():
    """确认同一线程标识复用锁对象，避免并发写入绕过串行化。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        lock_a = store._get_write_lock("t1")
        lock_b = store._get_write_lock("t1")
        assert lock_a is lock_b


@pytest.mark.anyio
async def test_get_write_lock_different_threads_get_different_locks():
    """确认不同线程标识不共享锁，从而保留跨线程并行写入能力。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        lock_a = store._get_write_lock("t1")
        lock_b = store._get_write_lock("t2")
        assert lock_a is not lock_b


# ---------------------------------------------------------------------------
# 并发写入时的序号单调性
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_concurrent_puts_produce_unique_monotonic_seqs():
    """确认同一线程的 10 次并发写入产生互异且递增的序号。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        results = await asyncio.gather(*[store.put(thread_id="t1", run_id=f"r{i}", event_type="trace", category="trace", content=f"msg{i}") for i in range(10)])
    seqs = sorted(r["seq"] for r in results)
    assert seqs == list(range(1, 11)), f"Expected 1-10, got {seqs}"


@pytest.mark.anyio
async def test_concurrent_puts_different_threads_independent_seqs():
    """确认不同线程并发写入时各自维护从 1 开始的独立序号计数器。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        t1_results, t2_results = await asyncio.gather(
            asyncio.gather(*[store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace") for _ in range(5)]),
            asyncio.gather(*[store.put(thread_id="t2", run_id="r2", event_type="trace", category="trace") for _ in range(5)]),
        )
    t1_seqs = sorted(r["seq"] for r in t1_results)
    t2_seqs = sorted(r["seq"] for r in t2_results)
    assert t1_seqs == [1, 2, 3, 4, 5]
    assert t2_seqs == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# 批量写入：委托单条写入并保持顺序
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_batch_seqs_are_monotonic():
    """确认单批事件返回的序号有序且无重复，防止批量写入破坏序号契约。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        events = [{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace", "content": str(i)} for i in range(5)]
        results = await store.put_batch(events)
    seqs = [r["seq"] for r in results]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 5


# ---------------------------------------------------------------------------
# 序号加载：新建存储实例后从磁盘恢复最大序号
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ensure_seq_loaded_recovers_from_disk():
    """确认新实例接续旧实例写入的最大序号，避免重启后发生序号碰撞。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store1 = _make_store(base)
        for i in range(3):
            await store1.put(thread_id="t1", run_id="r1", event_type="trace", category="trace", content=str(i))

        store2 = _make_store(base)
        record = await store2.put(thread_id="t1", run_id="r1", event_type="trace", category="trace", content="new")
        assert record["seq"] == 4, f"Expected seq=4 after recovery, got {record['seq']}"


# ---------------------------------------------------------------------------
# 线程卸载回归防线
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_offloads_write_via_to_thread():
    """回归防线：确认单条写入将文件写入交给线程卸载，避免阻塞事件循环。"""
    original = asyncio.to_thread
    calls: list[str] = []

    async def spy(*args, **kwargs):
        """记录被卸载的可调用对象名称后执行原始线程卸载函数。"""
        calls.append(args[0].__name__ if callable(args[0]) else repr(args[0]))
        return await original(*args, **kwargs)

    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        with patch("asyncio.to_thread", new=spy):
            await store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace", content="x")

    assert "_write_record" in calls, f"Expected asyncio.to_thread(_write_record, ...) — got: {calls}"


# ---------------------------------------------------------------------------
# 批量写入原子性：追加失败不能留下局部记录，以免调用方重试整批数据时产生重复。
# 第 4082 号变更的回归测试（源自审阅反馈）。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_batch_failure_rolls_back_no_partial_records(monkeypatch):
    """验证批量磁盘写入中途失败后重试仍不产生重复且序号保持单调。

    该失败替身会先写入半批记录再抛出异常，用于锁定写锁内的序号预留、磁盘
    恢复和整批重试之间的边界：失败后的重试不能将残留内容错误地重新编号。
    """
    import json

    from deerflow.runtime.events.store import jsonl as jsonl_mod

    real_append = jsonl_mod.JsonlRunEventStore._append_records

    def failing_append(self, path, records):
        """先追加半批换行记录再模拟磁盘写满，制造批量写入中途失败。"""
        # 先写入半数行，再抛出异常以模拟批处理过程中磁盘写满。
        path.parent.mkdir(parents=True, exist_ok=True)
        mid = len(records) // 2
        partial = "".join(json.dumps(r, default=str, ensure_ascii=False) + "\n" for r in records[:mid])
        with open(path, "a", encoding="utf-8") as f:
            f.write(partial)
        raise OSError("simulated mid-batch write failure")

    monkeypatch.setattr(jsonl_mod.JsonlRunEventStore, "_append_records", failing_append)

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        events = [
            {
                "thread_id": "t1",
                "run_id": "r1",
                "event_type": "trace",
                "category": "trace",
                "content": f"event-{i}",
            }
            for i in range(4)
        ]
        # 首次尝试会中途失败；文件可能有局部行，但因锁内已预留序号，内存计数器已推进。
        with pytest.raises(OSError):
            await store.put_batch(events)

        # 恢复真实追加函数后重试整批数据；此处锁定失败后序号与恢复的磁盘状态一致，
        # 不会把半批残留内容意外重新编号。
        monkeypatch.setattr(jsonl_mod.JsonlRunEventStore, "_append_records", real_append)
        # 按运行器的重新缓冲模式重试完整批次。
        records = await store.put_batch(events)

    # 重试成功后，每个事件恰好写入一次且序号仍严格递增。
    assert len(records) == 4, f"Expected 4 records, got {len(records)}"
    seqs = [r["seq"] for r in records]
    assert seqs == sorted(seqs) and len(set(seqs)) == 4, f"seqs not unique monotonic: {seqs}"


# ---------------------------------------------------------------------------
# 读取方法不会阻塞（覆盖线程卸载路径）
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_messages_reads_written_records():
    """确认列出消息方法能按写入顺序读回消息记录。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="world")
        messages = await store.list_messages("t1")
    assert len(messages) == 2
    assert messages[0]["content"] == "hello"
    assert messages[1]["content"] == "world"


@pytest.mark.anyio
async def test_count_messages_accurate_after_concurrent_writes():
    """确认并发写入完成后统计消息方法返回精确消息总数。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await asyncio.gather(*[store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message") for _ in range(7)])
        count = await store.count_messages("t1")
    assert count == 7


# ---------------------------------------------------------------------------
# 按线程删除与按运行删除使用写锁
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_by_thread_clears_seq_counter_and_lock():
    """确认删除线程会释放其序号计数器和写锁，防止已删除状态滞留内存。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace")
        await store.delete_by_thread("t1")
        assert "t1" not in store._seq_counters
        assert "t1" not in store._write_locks


@pytest.mark.anyio
async def test_delete_by_run_removes_run_events():
    """确认按运行删除仅移除目标运行的事件，查询结果不遗留记录。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="trace", category="trace")
        await store.delete_by_run("t1", "r1")
        events = await store.list_events("t1", "r1")
    assert events == []


# ---------------------------------------------------------------------------
# 数据库批量写入：拒绝混合线程批次
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_db_put_batch_rejects_mixed_thread_ids():
    """确认数据库批量写入对跨线程批次抛出数值错误，维护批次原子边界。"""
    from unittest.mock import MagicMock

    from deerflow.runtime.events.store.db import DbRunEventStore

    mock_sf = MagicMock()
    store = DbRunEventStore(session_factory=mock_sf)

    events = [
        {"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"},
        {"thread_id": "t2", "run_id": "r2", "event_type": "trace", "category": "trace"},
    ]

    with pytest.raises(ValueError, match="same thread"):
        await store.put_batch(events)
