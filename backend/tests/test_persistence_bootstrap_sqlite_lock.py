"""本模块覆盖持久化 SQLite的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

import gc
import weakref

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence.bootstrap import _get_sqlite_local_lock


def _make_engine():
    """准备可控测试资源与状态，供后续断言读取。"""
    return create_async_engine("sqlite+aiosqlite:///:memory:")


def test_cache_is_weak_key_dictionary() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    assert isinstance(bootstrap_mod._SQLITE_LOCKS, weakref.WeakKeyDictionary)


def test_same_engine_returns_same_lock() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _make_engine()
    assert _get_sqlite_local_lock(engine) is _get_sqlite_local_lock(engine)


def test_distinct_engines_get_distinct_locks() -> None:
    """验证获取在预期条件及边界场景下的可观察行为，防止相关回归。"""
    engine_a = _make_engine()
    engine_b = _make_engine()
    assert _get_sqlite_local_lock(engine_a) is not _get_sqlite_local_lock(engine_b)


def test_entry_drops_when_engine_is_garbage_collected() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _make_engine()
    _get_sqlite_local_lock(engine)
    assert engine in bootstrap_mod._SQLITE_LOCKS

    engine_ref = weakref.ref(engine)
    del engine
    gc.collect()

    assert engine_ref() is None, "engine should be collectible -- cache must not hold a strong ref"
    # WeakKeyDictionary may defer removal until the next access; touch it.
    assert all(ref() is not None for ref in bootstrap_mod._SQLITE_LOCKS.keyrefs())


@pytest.mark.asyncio
async def test_fresh_engine_gets_lock_usable_on_current_loop() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = _make_engine()
    try:
        lock = _get_sqlite_local_lock(engine)
        async with lock:
            pass
        # Re-entrant acquire on the same loop must also succeed.
        async with lock:
            pass
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cache_does_not_grow_across_disposed_engines() -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    initial = len(bootstrap_mod._SQLITE_LOCKS)
    for _ in range(20):
        engine = _make_engine()
        _get_sqlite_local_lock(engine)
        await engine.dispose()
        del engine
    gc.collect()
    # Touch the dict so WeakKeyDictionary clears any deferred removals.
    _ = list(bootstrap_mod._SQLITE_LOCKS.items())
    # Allow a small slack for any engine that is still pinned by a frame.
    assert len(bootstrap_mod._SQLITE_LOCKS) - initial <= 1
