"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence import bootstrap as bootstrap_mod

pytestmark = pytest.mark.asyncio


@pytest.mark.allow_blocking_io
async def test_bootstrap_offloads_alembic_stamp_and_upgrade(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    seen: list[str] = []

    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        seen.append(getattr(func, "__name__", repr(func)))
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(bootstrap_mod.asyncio, "to_thread", spy_to_thread)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    db_path = tmp_path / "spy.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    try:
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        await bootstrap_mod.bootstrap_schema(engine, backend="sqlite")
        assert "_stamp" in seen, f"_stamp not offloaded; saw: {seen}"

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        seen.clear()
        await bootstrap_mod.bootstrap_schema(engine, backend="sqlite")
        assert "_upgrade" in seen, f"_upgrade not offloaded; saw: {seen}"
    finally:
        await engine.dispose()
