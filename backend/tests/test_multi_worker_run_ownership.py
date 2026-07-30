"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.runs.manager import CancelOutcome, ConflictError, _generate_worker_id
from deerflow.runtime.runs.store.memory import MemoryRunStore

# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def _lease_config(**kwargs) -> RunOwnershipConfig:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return RunOwnershipConfig(
        lease_seconds=kwargs.get("lease_seconds", 30),
        grace_seconds=kwargs.get("grace_seconds", 10),
        heartbeat_enabled=kwargs.get("heartbeat_enabled", False),
    )


def _make_manager(store=None, **kwargs) -> RunManager:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return RunManager(
        store=store or MemoryRunStore(),
        run_ownership_config=kwargs.pop("run_ownership_config", _lease_config()),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reject_blocks_when_active_run_exists():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    await manager.create("thread-1")
    await manager.set_status((await manager.list_by_thread("thread-1"))[0].run_id, RunStatus.running)

    with pytest.raises(ConflictError, match="already has an active run"):
        await manager.create_or_reject("thread-1", multitask_strategy="reject")


@pytest.mark.anyio
async def test_reject_succeeds_when_no_active_run():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread-1", multitask_strategy="reject")
    assert record is not None
    assert record.status == RunStatus.pending
    assert record.owner_worker_id is not None
    assert record.lease_expires_at is not None


@pytest.mark.anyio
async def test_reject_blocks_reentrant_same_thread_locally():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    await manager.create_or_reject("thread-1", multitask_strategy="reject")

    with pytest.raises(ConflictError, match="already has an active run"):
        await manager.create_or_reject("thread-1", multitask_strategy="reject")


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_interrupt_cancels_old_run_and_creates_new():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    old = await manager.create_or_reject("thread-1", multitask_strategy="reject")
    await manager.set_status(old.run_id, RunStatus.running)

    new = await manager.create_or_reject("thread-1", multitask_strategy="interrupt")

    assert new.run_id != old.run_id
    assert new.status == RunStatus.pending

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert old.status == RunStatus.interrupted
    assert old.abort_event.is_set()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    old_after = await store.get(old.run_id)
    assert old_after["status"] == "interrupted"


@pytest.mark.anyio
async def test_interrupt_creates_new_when_old_completed():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    old = await manager.create_or_reject("thread-1")
    await manager.set_status(old.run_id, RunStatus.success)

    new = await manager.create_or_reject("thread-1", multitask_strategy="interrupt")
    assert new.run_id != old.run_id
    assert new.status == RunStatus.pending


@pytest.mark.anyio
async def test_interrupt_exhausted_retries_surface_as_conflict_error():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    import sqlite3

    class _AlwaysUniqueViolationStore(MemoryRunStore):
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

        def __init__(self):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            super().__init__()
            self.atomic_call_count = 0

        async def create_run_atomic(self, *args, **kwargs):
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self.atomic_call_count += 1
            err = sqlite3.IntegrityError("UNIQUE constraint failed: runs.uq_runs_thread_active")
            err.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_UNIQUE
            raise err

    store = _AlwaysUniqueViolationStore()
    manager = _make_manager(store=store)

    with pytest.raises(ConflictError, match="already has an active run"):
        await manager.create_or_reject("thread-1", multitask_strategy="interrupt")

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert store.atomic_call_count == 3


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_record_stores_owner_and_lease():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread-1")

    assert record.owner_worker_id == manager.worker_id
    assert isinstance(record.owner_worker_id, str) and len(record.owner_worker_id) > 0
    assert record.lease_expires_at is not None

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["owner_worker_id"] == manager.worker_id
    assert stored["lease_expires_at"] is not None


@pytest.mark.anyio
async def test_store_row_roundtrips_ownership_fields():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread-1")

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.owner_worker_id == manager.worker_id
    assert hydrated.lease_expires_at is not None


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconciliation_claims_expired_lease_runs():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "expired-run",
        thread_id="thread-1",
        status="running",
        owner_worker_id="worker-dead",
        lease_expires_at=expired_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert len(recovered) == 1
    assert recovered[0].run_id == "expired-run"
    assert recovered[0].status == RunStatus.error

    stored = await store.get("expired-run")
    assert stored["status"] == "error"


@pytest.mark.anyio
async def test_reconciliation_skips_active_lease_runs():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put(
        "live-run",
        thread_id="thread-1",
        status="running",
        owner_worker_id="worker-alive",
        lease_expires_at=valid_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert all(r.run_id != "live-run" for r in recovered)

    stored = await store.get("live-run")
    assert stored["status"] == "running"


@pytest.mark.anyio
async def test_reconciliation_claims_null_lease_runs():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    await store.put(
        "legacy-run",
        thread_id="thread-1",
        status="running",
        created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert len(recovered) == 1
    assert recovered[0].run_id == "legacy-run"


@pytest.mark.anyio
async def test_heartbeat_disabled_crashed_run_reclaimed_immediately():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    manager_a = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=False))
    record = await manager_a.create("thread-1")
    await manager_a.set_status(record.run_id, RunStatus.running)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["lease_expires_at"] is None

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    manager_b = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=False))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    recovered = await manager_b.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert len(recovered) == 1
    assert recovered[0].run_id == record.run_id
    assert recovered[0].status == RunStatus.error


@pytest.mark.anyio
async def test_reconciliation_skips_locally_active_runs():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert all(r.run_id != record.run_id for r in recovered)


@pytest.mark.anyio
async def test_reconciliation_returns_empty_when_no_orphaned_runs():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert recovered == []


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_heartbeat_renews_active_run_leases():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    record = await manager.create_or_reject("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    original_lease = record.lease_expires_at
    assert original_lease is not None

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await manager.start_heartbeat()
    await asyncio.sleep(0.2)  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    await manager._renew_leases()
    await manager.stop_heartbeat()

    assert record.lease_expires_at is not None
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert record.lease_expires_at >= original_lease


@pytest.mark.anyio
async def test_heartbeat_renews_pending_run_before_task_is_spawned():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    record = await manager.create_or_reject("thread-1")
    assert record.status == RunStatus.pending
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert record.task is None

    original_lease = record.lease_expires_at
    assert original_lease is not None

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await asyncio.sleep(0.001)

    store.update_lease = AsyncMock(wraps=store.update_lease)

    await manager._renew_leases()

    store.update_lease.assert_awaited_once()
    assert record.lease_expires_at is not None
    assert record.lease_expires_at > original_lease


@pytest.mark.anyio
async def test_heartbeat_skips_runs_not_owned_by_this_worker():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    old_lease = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    await store.put(
        "other-worker-run",
        thread_id="thread-1",
        status="running",
        owner_worker_id="other-worker",
        lease_expires_at=old_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    )

    await manager._renew_leases()

    stored = await store.get("other-worker-run")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert stored["lease_expires_at"] == old_lease


@pytest.mark.anyio
async def test_heartbeat_not_started_when_disabled():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = _lease_config(heartbeat_enabled=False)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    assert manager.heartbeat_enabled is False
    await manager.start_heartbeat()
    assert manager._heartbeat_task is None
    assert manager._heartbeat_stop is None


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_local_run_succeeds():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    result = await manager.cancel(record.run_id)
    assert result == CancelOutcome.cancelled
    assert record.status == RunStatus.interrupted


@pytest.mark.anyio
async def test_cancel_unknown_run_returns_false():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    result = await manager.cancel("nonexistent-run")
    assert result == CancelOutcome.not_active_locally


@pytest.mark.anyio
async def test_cancel_idempotent():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.interrupted)

    result = await manager.cancel(record.run_id)
    assert result == CancelOutcome.cancelled


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_worker_default_config_behavior_unchanged():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    config = _lease_config(heartbeat_enabled=False)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    r1 = await manager.create("thread-1")
    assert r1.owner_worker_id is not None

    r2 = await manager.create_or_reject("thread-2", multitask_strategy="reject")
    assert r2.owner_worker_id is not None

    await manager.cancel(r2.run_id)
    stored = await store.get(r2.run_id)
    assert stored["status"] == "interrupted"


@pytest.mark.anyio
async def test_manager_without_run_ownership_config():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    manager = RunManager(store=store)  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    record = await manager.create_or_reject("thread-1")
    assert record is not None
    assert record.owner_worker_id is not None  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert manager.heartbeat_enabled is False
    await manager.start_heartbeat()
    assert manager._heartbeat_task is None


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_worker_id_is_generated():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    wid = _generate_worker_id()
    assert isinstance(wid, str)
    assert len(wid) > 0
    assert ":" in wid


def test_two_managers_have_different_default_ids():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    m1 = RunManager()
    m2 = RunManager()
    assert m1.worker_id != m2.worker_id


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_run_atomic_reject_prevents_duplicate():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    config = _lease_config()

    store.create_run_atomic = AsyncMock(wraps=store.create_run_atomic)

    await store.create_run_atomic(
        run_id="run-1",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    with pytest.raises(ConflictError, match="already has an active run"):
        await store.create_run_atomic(
            run_id="run-2",
            thread_id="thread-1",
            owner_worker_id="w2",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            multitask_strategy="reject",
            grace_seconds=config.grace_seconds,
        )


@pytest.mark.anyio
async def test_create_run_atomic_interrupt_claims_and_creates():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    config = _lease_config()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()

    await store.create_run_atomic(
        run_id="run-old",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=expired_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    new_row, claimed = await store.create_run_atomic(
        run_id="run-new",
        thread_id="thread-1",
        owner_worker_id="w2",
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        multitask_strategy="interrupt",
        grace_seconds=config.grace_seconds,
    )

    assert new_row["run_id"] == "run-new"
    assert new_row["status"] == "pending"
    assert len(claimed) == 1
    assert claimed[0]["run_id"] == "run-old"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    old_row = await store.get("run-old")
    assert old_row["status"] == "interrupted"


@pytest.mark.anyio
async def test_create_run_atomic_interrupt_rejects_other_worker_valid_lease():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    await store.create_run_atomic(
        run_id="valid-lease-run",
        thread_id="thread-1",
        owner_worker_id="other-worker",
        lease_expires_at=valid_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    with pytest.raises(ConflictError, match="another worker"):
        await store.create_run_atomic(
            run_id="run-new",
            thread_id="thread-1",
            owner_worker_id="w2",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            multitask_strategy="interrupt",
            grace_seconds=config.grace_seconds,
        )

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    old_row = await store.get("valid-lease-run")
    assert old_row["status"] == "pending"
    assert old_row["owner_worker_id"] == "other-worker"


@pytest.mark.anyio
async def test_create_run_atomic_interrupt_allows_self_owned_valid_lease():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    await store.create_run_atomic(
        run_id="self-run",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=valid_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    new_row, claimed = await store.create_run_atomic(
        run_id="run-new",
        thread_id="thread-1",
        owner_worker_id="w1",  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        multitask_strategy="interrupt",
        grace_seconds=config.grace_seconds,
    )

    assert new_row["run_id"] == "run-new"
    assert len(claimed) == 1
    assert claimed[0]["run_id"] == "self-run"
    assert claimed[0]["status"] == "interrupted"


@pytest.mark.anyio
async def test_create_run_atomic_interrupt_rolls_back_earlier_mutations_on_conflict():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put(
        "expired-run",
        thread_id="thread-1",
        status="pending",
        owner_worker_id="old-worker",
        lease_expires_at=expired_lease,
    )
    await store.put(
        "valid-lease-run",
        thread_id="thread-1",
        status="pending",
        owner_worker_id="other-worker",
        lease_expires_at=valid_lease,
    )

    with pytest.raises(ConflictError, match="another worker"):
        await store.create_run_atomic(
            run_id="run-new",
            thread_id="thread-1",
            owner_worker_id="w1",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            multitask_strategy="interrupt",
            grace_seconds=config.grace_seconds,
        )

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    expired_row = await store.get("expired-run")
    assert expired_row["status"] == "pending"
    assert expired_row["owner_worker_id"] == "old-worker"
    assert expired_row["error"] is None

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    valid_row = await store.get("valid-lease-run")
    assert valid_row["status"] == "pending"
    assert valid_row["owner_worker_id"] == "other-worker"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert await store.get("run-new") is None


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_lease_renews_row():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    old_lease = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    await store.put(
        "run-1",
        thread_id="thread-1",
        status="running",
        owner_worker_id="w1",
        lease_expires_at=old_lease,
    )

    new_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    updated = await store.update_lease(
        "run-1",
        owner_worker_id="w1",
        lease_expires_at=new_lease,
    )
    assert updated is True

    stored = await store.get("run-1")
    assert stored["lease_expires_at"] == new_lease


@pytest.mark.anyio
async def test_update_lease_returns_false_for_terminal_run():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    await store.put("run-1", thread_id="thread-1", status="success", owner_worker_id="w1")

    new_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    updated = await store.update_lease(
        "run-1",
        owner_worker_id="w1",
        lease_expires_at=new_lease,
    )
    assert updated is False

    stored = await store.get("run-1")
    assert stored["status"] == "success"


@pytest.mark.anyio
async def test_update_lease_returns_false_for_wrong_owner():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    old_lease = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    await store.put(
        "run-1",
        thread_id="thread-1",
        status="running",
        owner_worker_id="w1",
        lease_expires_at=old_lease,
    )

    new_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    updated = await store.update_lease(
        "run-1",
        owner_worker_id="w2",  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        lease_expires_at=new_lease,
    )
    assert updated is False

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    stored = await store.get("run-1")
    assert stored["owner_worker_id"] == "w1"
    assert stored["lease_expires_at"] == old_lease


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_filters_correctly():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    now = datetime.now(UTC)
    grace = 10

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    expired = (now - timedelta(seconds=60)).isoformat()
    await store.put("expired-run", thread_id="t1", status="running", owner_worker_id="w1", lease_expires_at=expired, created_at=expired)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    valid = (now + timedelta(seconds=60)).isoformat()
    await store.put("valid-run", thread_id="t2", status="running", owner_worker_id="w2", lease_expires_at=valid, created_at=valid)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("null-lease-run", thread_id="t3", status="running", created_at=(now - timedelta(seconds=30)).isoformat())

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("success-run", thread_id="t4", status="success", created_at=(now - timedelta(seconds=60)).isoformat())

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)

    result_ids = {r["run_id"] for r in results}
    assert "expired-run" in result_ids
    assert "null-lease-run" in result_ids
    assert "valid-run" not in result_ids
    assert "success-run" not in result_ids


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_compares_created_at_as_datetime():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    now = datetime.now(UTC)
    grace = 10

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("recent-run", thread_id="t1", status="running", created_at=now.isoformat())
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    far_future = "2300-01-01T00:00:00+00:00"
    await store.put("future-run", thread_id="t2", status="running", created_at=far_future)

    results = await store.list_inflight_with_expired_lease(before=now.isoformat(), grace_seconds=grace)
    result_ids = {r["run_id"] for r in results}
    assert "recent-run" in result_ids
    assert "future-run" not in result_ids


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_handles_malformed_created_at():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10

    store._runs["bad-run"] = {
        "run_id": "bad-run",
        "thread_id": "t1",
        "status": "running",
        "created_at": "not-a-datetime",
    }
    store._runs["empty-run"] = {
        "run_id": "empty-run",
        "thread_id": "t2",
        "status": "running",
        "created_at": "",
    }

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    result_ids = {r["run_id"] for r in results}
    assert "bad-run" not in result_ids
    assert "empty-run" not in result_ids


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_datetime_aware_naive_handling():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    now = datetime.now(UTC)
    grace = 10

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    naive_expired = (now - timedelta(seconds=60)).isoformat()  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("naive-run", thread_id="t1", status="running", lease_expires_at=naive_expired, created_at=naive_expired)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    aware_expired = (now - timedelta(seconds=60)).replace(tzinfo=UTC).isoformat()  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("aware-run", thread_id="t2", status="running", lease_expires_at=aware_expired, created_at=aware_expired)

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)
    result_ids = {r["run_id"] for r in results}
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert "naive-run" in result_ids
    assert "aware-run" in result_ids


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_null_lease_always_reclaimed():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("null-run", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)
    result_ids = {r["run_id"] for r in results}
    assert "null-run" in result_ids


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_claim_for_takeover_succeeds_with_expired_lease():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put("run-1", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=expired_lease)

    ok = await store.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
    assert ok is True

    row = await store.get("run-1")
    assert row is not None
    assert row["status"] == "error"
    assert row["error"] == "claimed"


@pytest.mark.anyio
async def test_claim_for_takeover_fails_with_valid_lease():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put("run-1", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=valid_lease)

    ok = await store.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
    assert ok is False

    row = await store.get("run-1")
    assert row is not None
    assert row["status"] == "running"


@pytest.mark.anyio
async def test_claim_for_takeover_succeeds_with_null_lease():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    await store.put("run-null", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

    ok = await store.claim_for_takeover("run-null", grace_seconds=10, error="claimed")
    assert ok is True

    row = await store.get("run-null")
    assert row["status"] == "error"


@pytest.mark.anyio
async def test_claim_for_takeover_fails_on_terminal_status():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    await store.put("run-done", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())

    ok = await store.claim_for_takeover("run-done", grace_seconds=10, error="claimed")
    assert ok is False


@pytest.mark.anyio
async def test_claim_for_takeover_fails_for_nonexistent_run():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    ok = await store.claim_for_takeover("no-such-run", grace_seconds=10, error="claimed")
    assert ok is False


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_takeover_from_crashed_worker():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put("run-expired", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="dead-worker", lease_expires_at=expired_lease)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-expired")
    assert outcome == CancelOutcome.taken_over

    row = await store.get("run-expired")
    assert row is not None
    assert row["status"] == "error"


@pytest.mark.anyio
async def test_cancel_refuses_active_lease_from_other_worker():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put("run-alive", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="alive-worker", lease_expires_at=valid_lease)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-alive")
    assert outcome == CancelOutcome.lease_valid_elsewhere

    row = await store.get("run-alive")
    assert row is not None
    assert row["status"] == "running"  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


@pytest.mark.anyio
async def test_cancel_returns_unknown_when_no_store():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    manager = _make_manager(run_ownership_config=_lease_config(heartbeat_enabled=True))
    outcome = await manager.cancel("no-such-run")
    assert outcome == CancelOutcome.unknown


@pytest.mark.anyio
async def test_cancel_returns_not_active_locally_when_heartbeat_disabled():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    await store.put("store-only", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=False))
    outcome = await manager.cancel("store-only")
    assert outcome == CancelOutcome.not_active_locally


@pytest.mark.anyio
async def test_cancel_takeover_race_owner_renewed_lease():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put("run-race", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=expired_lease)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    original = store.claim_for_takeover

    async def race_lost(run_id, *, grace_seconds, error):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        run = store._runs.get(run_id)
        if run and run["status"] in ("pending", "running"):
            run["lease_expires_at"] = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
        return await original(run_id, grace_seconds=grace_seconds, error=error)

    store.claim_for_takeover = race_lost
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))

    outcome = await manager.cancel("run-race")
    assert outcome == CancelOutcome.lease_valid_elsewhere


@pytest.mark.anyio
async def test_cancel_takeover_respects_grace_seconds():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    just_expired = (datetime.now(UTC) - timedelta(seconds=3)).isoformat()
    await store.put("run-grace", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=just_expired)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-grace")
    assert outcome == CancelOutcome.lease_valid_elsewhere


@pytest.mark.anyio
async def test_cancel_not_cancellable_for_store_terminal_run():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    await store.put("run-done", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    outcome = await manager.cancel("run-done")
    assert outcome == CancelOutcome.not_cancellable


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def _make_cancel_test_app(mgr: RunManager):
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    from _router_auth_helpers import make_authed_test_app
    from fastapi.testclient import TestClient

    from app.gateway.routers import thread_runs
    from deerflow.runtime import MemoryStreamBridge

    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_manager = mgr
    app.state.stream_bridge = MemoryStreamBridge()
    return TestClient(app, raise_server_exceptions=False)


def test_http_cancel_non_owner_valid_lease_returns_409_with_retry_after():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    asyncio.run(
        store.put(
            "run-alive",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="alive-worker",
            lease_expires_at=valid_lease,
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    resp = client.post("/api/threads/t1/runs/run-alive/cancel")
    assert resp.status_code == 409
    assert "Retry-After" in resp.headers
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    retry_after = int(resp.headers["Retry-After"])
    assert 50 <= retry_after <= 75

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    row = asyncio.run(store.get("run-alive"))
    assert row["status"] == "running"


def test_http_cancel_non_owner_expired_lease_returns_202_takeover():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 30)).isoformat()
    asyncio.run(
        store.put(
            "run-dead",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="dead-worker",
            lease_expires_at=expired_lease,
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    resp = client.post("/api/threads/t1/runs/run-dead/cancel")
    assert resp.status_code == 202

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    row = asyncio.run(store.get("run-dead"))
    assert row["status"] == "error"


def test_http_stream_action_interrupt_takeover_returns_202_not_hang():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 30)).isoformat()
    asyncio.run(
        store.put(
            "run-dead-stream",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="dead-worker",
            lease_expires_at=expired_lease,
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    resp = client.post("/api/threads/t1/runs/run-dead-stream/stream", params={"action": "interrupt"})
    assert resp.status_code == 202

    row = asyncio.run(store.get("run-dead-stream"))
    assert row["status"] == "error"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_status_rejects_terminal_row():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("run-err", thread_id="t1", status="error", created_at=datetime.now(UTC).isoformat())
    assert await store.update_status("run-err", "success") is False
    assert (await store.get("run-err"))["status"] == "error"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("run-ok", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())
    assert await store.update_status("run-ok", "error") is False
    assert (await store.get("run-ok"))["status"] == "success"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.put("run-rb", thread_id="t1", status="interrupted", created_at=datetime.now(UTC).isoformat())
    assert await store.update_status("run-rb", "error", error="Rolled back by user") is True
    row = await store.get("run-rb")
    assert row["status"] == "error"
    assert row["error"] == "Rolled back by user"


@pytest.mark.anyio
async def test_persist_status_skips_recovery_when_row_taken_over():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.update_status(record.run_id, "error")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    ok = await mgr._persist_status(record, RunStatus.success)
    assert ok is False  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    row = await store.get(record.run_id)
    assert row["status"] == "error"  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


@pytest.mark.anyio
async def test_heartbeat_cancels_task_on_lease_loss():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, lease_seconds=30))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    loop = asyncio.get_running_loop()
    record.task = loop.create_task(asyncio.sleep(3600))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await store.update_status(record.run_id, "error")

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await mgr._renew_leases()

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await asyncio.sleep(0)
    assert record.task.cancelled()


@pytest.mark.anyio
async def test_cancel_returns_taken_over_when_peer_claims_during_local_cancel():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))

    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    original = store.update_status

    async def race_update(run_id, status, *, error=None, stop_reason=None):
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        run = store._runs.get(run_id)
        if run and run["status"] == "running" and status == "interrupted":
            run["status"] = "error"
            run["error"] = "peer takeover"
            run["updated_at"] = datetime.now(UTC).isoformat()
            return False  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        return await original(run_id, status, error=error, stop_reason=stop_reason)

    store.update_status = race_update

    outcome = await mgr.cancel(record.run_id)
    assert outcome == CancelOutcome.taken_over

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    row = await store.get(record.run_id)
    assert row["status"] == "error"


@pytest.mark.anyio
async def test_cancel_action_rollback_finalizes_to_error_in_store():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))

    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    outcome = await mgr.cancel(record.run_id, action="rollback")
    assert outcome == CancelOutcome.cancelled
    row = await store.get(record.run_id)
    assert row["status"] == "interrupted"

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    await mgr.set_status(record.run_id, RunStatus.error, error="Rolled back by user")
    row = await store.get(record.run_id)
    assert row["status"] == "error"
    assert row["error"] == "Rolled back by user"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_claim_lost_to_terminal_returns_not_cancellable():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=10))

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    expired = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "run-race",
        thread_id="t1",
        status="running",
        owner_worker_id="w-a",
        lease_expires_at=expired,
        created_at=datetime.now(UTC).isoformat(),
    )

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    original = store.claim_for_takeover

    async def race_claim(run_id, *, grace_seconds, error):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        store._runs[run_id]["status"] = "success"
        return await original(run_id, grace_seconds=grace_seconds, error=error)

    store.claim_for_takeover = race_claim

    outcome = await mgr.cancel("run-race")
    assert outcome == CancelOutcome.not_cancellable


@pytest.mark.anyio
async def test_cancel_claim_lost_to_takeover_returns_taken_over():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=10))

    expired = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "run-race",
        thread_id="t1",
        status="running",
        owner_worker_id="w-a",
        lease_expires_at=expired,
        created_at=datetime.now(UTC).isoformat(),
    )

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    original = store.claim_for_takeover

    async def race_takeover(run_id, *, grace_seconds, error):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        store._runs[run_id]["status"] = "error"
        store._runs[run_id]["error"] = "peer claim"
        return await original(run_id, grace_seconds=grace_seconds, error=error)

    store.claim_for_takeover = race_takeover

    outcome = await mgr.cancel("run-race")
    assert outcome == CancelOutcome.taken_over


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_compute_retry_after_null_lease_returns_none():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from app.gateway.routers.thread_runs import _compute_retry_after

    assert _compute_retry_after(None, 10) is None


def test_compute_retry_after_unparseable_returns_none():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from app.gateway.routers.thread_runs import _compute_retry_after

    assert _compute_retry_after("not-a-date", 10) is None


def test_compute_retry_after_normal():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from app.gateway.routers.thread_runs import _compute_retry_after

    future = (datetime.now(UTC) + timedelta(seconds=45)).isoformat()
    val = _compute_retry_after(future, 10)
    assert val is not None
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert 40 <= val <= 65


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_http_stream_action_interrupt_non_owner_returns_409_with_retry_after():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    asyncio.run(
        store.put(
            "run-alive-stream",
            thread_id="t1",
            status="running",
            owner_worker_id="alive-worker",
            lease_expires_at=valid_lease,
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    resp = client.post("/api/threads/t1/runs/run-alive-stream/stream", params={"action": "interrupt"})
    assert resp.status_code == 409
    assert "Retry-After" in resp.headers
    retry_after = int(resp.headers["Retry-After"])
    assert 50 <= retry_after <= 75
