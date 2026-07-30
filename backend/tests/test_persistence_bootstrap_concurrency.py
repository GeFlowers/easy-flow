"""本模块覆盖持久化的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence.bootstrap import bootstrap_schema

pytestmark = pytest.mark.asyncio


HEAD = "0005_run_stop_reason"


def _url(tmp_path: Path) -> str:
    """准备可控测试资源与状态，供后续断言读取。"""
    return f"sqlite+aiosqlite:///{(tmp_path / 'concurrent.db').as_posix()}"


async def _alembic_version(engine) -> str | None:
    """准备可控测试资源与状态，供后续断言读取。"""
    async with engine.connect() as conn:
        row = await conn.execute(sa.text("SELECT version_num FROM alembic_version"))
        return row.scalar()


async def _runs_columns(engine) -> set[str]:
    """准备可控测试资源与状态，供后续断言读取。"""
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: {col["name"] for col in sa.inspect(c).get_columns("runs")})


async def test_two_concurrent_bootstrap_callers_converge(tmp_path: Path) -> None:
    """验证并发在预期条件及边界场景下的可观察行为，防止相关回归。"""
    engine = create_async_engine(_url(tmp_path))
    try:
        await asyncio.gather(
            bootstrap_schema(engine, backend="sqlite"),
            bootstrap_schema(engine, backend="sqlite"),
        )
        assert await _alembic_version(engine) == HEAD
        assert "token_usage_by_model" in await _runs_columns(engine)
    finally:
        await engine.dispose()


async def test_five_concurrent_bootstrap_callers_converge(tmp_path: Path) -> None:
    """验证并发在预期条件及边界场景下的可观察行为，防止相关回归。"""
    engine = create_async_engine(_url(tmp_path))
    try:
        await asyncio.gather(*(bootstrap_schema(engine, backend="sqlite") for _ in range(5)))
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


async def test_cancelled_caller_does_not_block_others(tmp_path: Path) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = create_async_engine(_url(tmp_path))
    try:
        task = asyncio.create_task(bootstrap_schema(engine, backend="sqlite"))
        # Give the event loop a turn so the task can start; then cancel.
        await asyncio.sleep(0)
        task.cancel()
        # Cancelled task may have raced past the lock; swallow either outcome.
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

        # Lock must be free for the next caller.
        await bootstrap_schema(engine, backend="sqlite")
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


async def test_late_caller_after_head_is_noop(monkeypatch, tmp_path: Path) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    engine = create_async_engine(_url(tmp_path))
    try:
        # First caller: empty branch.
        await bootstrap_schema(engine, backend="sqlite")
        first_version = await _alembic_version(engine)
        assert first_version == HEAD

        upgrade_calls: list[str] = []
        original_upgrade = bootstrap_mod._upgrade

        def counting_upgrade(cfg, rev: str) -> None:
            """准备可控测试资源与状态，供后续断言读取。"""
            upgrade_calls.append(rev)
            original_upgrade(cfg, rev)

        monkeypatch.setattr(bootstrap_mod, "_upgrade", counting_upgrade)

        # Second caller: versioned branch -> calls _upgrade('head').
        await bootstrap_schema(engine, backend="sqlite")
        assert upgrade_calls == ["head"]
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


async def test_slow_upgrade_does_not_corrupt_concurrent_state(monkeypatch, tmp_path: Path) -> None:
    """验证并发 状态在预期条件及边界场景下的可观察行为，防止相关回归。"""
    engine = create_async_engine(_url(tmp_path))
    try:
        original_upgrade = bootstrap_mod._upgrade

        def slow_upgrade(cfg, rev: str) -> None:
            """准备可控测试资源与状态，供后续断言读取。"""
            import time  # noqa: PLC0415

            time.sleep(0.2)
            original_upgrade(cfg, rev)

        monkeypatch.setattr(bootstrap_mod, "_upgrade", slow_upgrade)

        await asyncio.gather(
            bootstrap_schema(engine, backend="sqlite"),
            bootstrap_schema(engine, backend="sqlite"),
            bootstrap_schema(engine, backend="sqlite"),
        )
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()
