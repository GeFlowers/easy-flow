"""覆盖本文件测试的输入约束、模拟边界与回归保护，确保测试仅记录既有行为。"""

from __future__ import annotations

import pytest

from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore


async def _seed_ai_messages(store):
    """构造测试所需的受控前置条件，隔离外部资源并保持断言可重复。"""
    await store.put(
        thread_id="t1",
        run_id="r1",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "content": "first"},
        metadata={"caller": "lead_agent"},
    )
    await store.put(
        thread_id="t1",
        run_id="r1",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "content": "middleware"},
        metadata={"caller": "middleware:title"},
    )
    last = await store.put(
        thread_id="t1",
        run_id="r1",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "content": "last"},
        metadata={"caller": "lead_agent"},
    )
    other = await store.put(
        thread_id="t1",
        run_id="r2",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "content": "other"},
        metadata={"caller": "lead_agent"},
    )
    await store.put(
        thread_id="t1",
        run_id="r_mw",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "content": "middleware only"},
        metadata={"caller": "middleware:title"},
    )
    return {"r1": last["seq"], "r2": other["seq"]}


@pytest.mark.anyio
async def test_memory_event_store_returns_global_last_non_middleware_ai_seq():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    store = MemoryRunEventStore()
    expected = await _seed_ai_messages(store)
    result = await store.get_last_visible_ai_seq_by_run("t1", {"r1", "r2", "r_mw", "missing"})
    assert result == expected
    assert "r_mw" not in result


@pytest.mark.anyio
async def test_memory_event_store_defensively_rechecks_message_category():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    store = MemoryRunEventStore()
    expected = await store.put(
        thread_id="t1",
        run_id="r1",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "content": "visible"},
        metadata={"caller": "lead_agent"},
    )
    mutated = await store.put(
        thread_id="t1",
        run_id="r1",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "content": "no longer a message"},
        metadata={"caller": "lead_agent"},
    )
    # 此处说明下方测试的前置条件与预期，便于回归时定位断言所保护的行为边界。
    # 此处说明下方测试的前置条件与预期，便于回归时定位断言所保护的行为边界。
    # 此处说明下方测试的前置条件与预期，便于回归时定位断言所保护的行为边界。
    mutated["category"] = "trace"

    assert await store.get_last_visible_ai_seq_by_run("t1", {"r1"}) == {"r1": expected["seq"]}


@pytest.mark.anyio
async def test_jsonl_event_store_returns_global_last_non_middleware_ai_seq(tmp_path):
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

    store = JsonlRunEventStore(base_dir=tmp_path)
    expected = await _seed_ai_messages(store)
    result = await store.get_last_visible_ai_seq_by_run("t1", {"r1", "r2", "r_mw", "missing"})
    assert result == expected
    assert "r_mw" not in result


@pytest.mark.anyio
async def test_db_event_store_returns_global_last_non_middleware_ai_seq(tmp_path):
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'events.db'}", sqlite_dir=str(tmp_path))
    try:
        store = DbRunEventStore(get_session_factory())
        expected = await _seed_ai_messages(store)
        result = await store.get_last_visible_ai_seq_by_run("t1", {"r1", "r2", "r_mw", "missing"})
        assert result == expected
        assert "r_mw" not in result
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_memory_run_store_supersession_is_unbounded_and_owner_scoped():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    store = MemoryRunStore()
    for index in range(105):
        await store.put(f"normal-{index}", thread_id="t1", user_id="alice", status="success")
    await store.put(
        "regen-success",
        thread_id="t1",
        user_id="alice",
        status="success",
        metadata={"regenerate_from_run_id": "source-success"},
    )
    await store.put(
        "regen-failed",
        thread_id="t1",
        user_id="alice",
        status="error",
        metadata={"regenerate_from_run_id": "source-failed"},
    )
    await store.put(
        "regen-bob",
        thread_id="t1",
        user_id="bob",
        status="success",
        metadata={"regenerate_from_run_id": "source-bob"},
    )

    assert await store.list_successful_regenerate_sources("t1", user_id="alice") == {"source-success"}


@pytest.mark.anyio
async def test_run_repository_batch_queries_are_unbounded_and_owner_scoped(tmp_path):
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}", sqlite_dir=str(tmp_path))
    try:
        repo = RunRepository(get_session_factory())
        for index in range(105):
            await repo.put(f"normal-{index}", thread_id="t1", user_id="alice", status="success")
        await repo.put(
            "regen-a",
            thread_id="t1",
            user_id="alice",
            status="success",
            metadata={"regenerate_from_run_id": "source-a"},
        )
        await repo.put(
            "regen-b",
            thread_id="t1",
            user_id="bob",
            status="success",
            metadata={"regenerate_from_run_id": "source-b"},
        )

        assert await repo.list_successful_regenerate_sources("t1", user_id="alice") == {"source-a"}
        rows = await repo.get_many_by_thread("t1", {"normal-0", "regen-a", "regen-b"}, user_id="alice")
        assert set(rows) == {"normal-0", "regen-a"}
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_run_manager_prefers_latest_in_memory_regenerate_status():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    store = MemoryRunStore()
    await store.put(
        "regen",
        thread_id="t1",
        status="success",
        metadata={"regenerate_from_run_id": "source"},
    )
    manager = RunManager(store=store)
    # 此处说明下方测试的前置条件与预期，便于回归时定位断言所保护的行为边界。
    # 此处说明下方测试的前置条件与预期，便于回归时定位断言所保护的行为边界。
    persisted = await manager.get("regen")
    assert persisted is not None
    manager._runs["regen"] = persisted
    manager._index_run_locked(persisted)
    persisted.status = RunStatus.error

    assert await manager.list_successful_regenerate_sources("t1", user_id=None) == set()


@pytest.mark.anyio
async def test_run_manager_uses_latest_attempt_for_shared_regenerate_source():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    manager = RunManager()
    older = await manager.create(
        "t1",
        metadata={"regenerate_from_run_id": "source"},
    )
    older.status = RunStatus.success
    newer = await manager.create(
        "t1",
        metadata={"regenerate_from_run_id": "source"},
    )
    newer.status = RunStatus.error

    assert await manager.list_successful_regenerate_sources("t1", user_id=None) == set()


@pytest.mark.anyio
async def test_run_manager_batch_history_methods_default_to_current_user():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    from types import SimpleNamespace

    from deerflow.runtime.user_context import reset_current_user, set_current_user

    store = MemoryRunStore()
    await store.put(
        "regen-alice",
        thread_id="shared-thread",
        user_id="alice",
        status="success",
        metadata={"regenerate_from_run_id": "source-alice"},
    )
    await store.put(
        "regen-bob",
        thread_id="shared-thread",
        user_id="bob",
        status="success",
        metadata={"regenerate_from_run_id": "source-bob"},
    )
    manager = RunManager(store=store)
    token = set_current_user(SimpleNamespace(id="alice"))
    try:
        sources = await manager.list_successful_regenerate_sources("shared-thread")
        records = await manager.get_many_by_thread("shared-thread", {"regen-alice", "regen-bob"})
    finally:
        reset_current_user(token)

    assert sources == {"source-alice"}
    assert set(records) == {"regen-alice"}


@pytest.mark.anyio
async def test_run_manager_batch_history_methods_fail_closed_without_user_context():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    from deerflow.runtime import user_context

    manager = RunManager(store=MemoryRunStore())
    token = user_context._current_user.set(None)
    try:
        with pytest.raises(RuntimeError, match="user_id=AUTO"):
            await manager.list_successful_regenerate_sources("t1")
        with pytest.raises(RuntimeError, match="user_id=AUTO"):
            await manager.get_many_by_thread("t1", {"run-1"})
    finally:
        user_context._current_user.reset(token)


@pytest.mark.anyio
async def test_run_manager_batch_history_methods_allow_explicit_unscoped_access():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    store = MemoryRunStore()
    await store.put(
        "regen-alice",
        thread_id="shared-thread",
        user_id="alice",
        status="success",
        metadata={"regenerate_from_run_id": "source-alice"},
    )
    await store.put(
        "regen-bob",
        thread_id="shared-thread",
        user_id="bob",
        status="success",
        metadata={"regenerate_from_run_id": "source-bob"},
    )
    manager = RunManager(store=store)

    sources = await manager.list_successful_regenerate_sources("shared-thread", user_id=None)
    records = await manager.get_many_by_thread("shared-thread", {"regen-alice", "regen-bob"}, user_id=None)

    assert sources == {"source-alice", "source-bob"}
    assert set(records) == {"regen-alice", "regen-bob"}
