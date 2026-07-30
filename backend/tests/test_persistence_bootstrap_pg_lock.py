"""本模块覆盖持久化的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

import pytest

from deerflow.persistence import bootstrap as bootstrap_mod


class _FakeAsyncConn:
    """集中覆盖当前测试分支与回归边界。"""

    def __init__(self) -> None:
        """准备可控测试资源与状态，供后续断言读取。"""
        self.executed: list[tuple[str, dict | None]] = []

    async def execute(self, stmt, params=None):
        """准备可控测试资源与状态，供后续断言读取。"""
        self.executed.append((str(stmt), params))
        return None

    async def __aenter__(self) -> _FakeAsyncConn:
        """准备可控测试资源与状态，供后续断言读取。"""
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """准备可控测试资源与状态，供后续断言读取。"""
        return None


class _FakeAsyncEngine:
    """集中覆盖当前测试分支与回归边界。"""
    def __init__(self) -> None:
        """准备可控测试资源与状态，供后续断言读取。"""
        self.conn = _FakeAsyncConn()

    def connect(self) -> _FakeAsyncConn:
        """准备可控测试资源与状态，供后续断言读取。"""
        return self.conn


@pytest.mark.asyncio
async def test_postgres_lock_disables_idle_in_transaction_kill_before_locking() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _FakeAsyncEngine()

    async with bootstrap_mod._postgres_lock(engine):  # type: ignore[arg-type]
        pass

    sqls = [stmt for stmt, _ in engine.conn.executed]

    # 1. SET LOCAL fires.
    set_local_idx = next(
        (i for i, s in enumerate(sqls) if "set local idle_in_transaction_session_timeout" in s.lower()),
        None,
    )
    assert set_local_idx is not None, f"SET LOCAL never executed; saw: {sqls}"
    assert "0" in sqls[set_local_idx], f"SET LOCAL did not target value 0: {sqls[set_local_idx]!r}"

    # 2. SET LOCAL precedes pg_advisory_lock.
    lock_idx = next((i for i, s in enumerate(sqls) if "pg_advisory_lock" in s), None)
    assert lock_idx is not None, f"pg_advisory_lock never executed; saw: {sqls}"
    assert set_local_idx < lock_idx, f"SET LOCAL must run before pg_advisory_lock; got order {sqls}"

    # 3. pg_advisory_unlock still fires on exit.
    assert any("pg_advisory_unlock" in s for s in sqls), f"pg_advisory_unlock missing; saw: {sqls}"


@pytest.mark.asyncio
async def test_postgres_lock_releases_even_if_body_raises() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _FakeAsyncEngine()

    with pytest.raises(RuntimeError, match="boom"):
        async with bootstrap_mod._postgres_lock(engine):  # type: ignore[arg-type]
            raise RuntimeError("boom")

    sqls = [stmt for stmt, _ in engine.conn.executed]
    assert any("pg_advisory_unlock" in s for s in sqls), f"unlock missing after body error; saw: {sqls}"
