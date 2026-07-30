"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from blockbuster import BlockingError
from support.detectors.blocking_io_runtime import detect_blocking_io_strict

pytestmark = pytest.mark.asyncio


async def test_gate_catches_unoffloaded_blocking_io_in_deerflow_module(tmp_path: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir

    db_file = tmp_path / "subdir" / "store.db"

    with pytest.raises(BlockingError):
        ensure_sqlite_parent_dir(str(db_file))


async def test_gate_restores_blockbuster_patches_after_exceptions() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    original_stat = os.stat

    with pytest.raises(RuntimeError, match="boom"):
        with detect_blocking_io_strict():
            raise RuntimeError("boom")

    assert os.stat is original_stat


@pytest.mark.allow_blocking_io
async def test_allow_blocking_io_marker_opts_out_of_gate(tmp_path: Path) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir

    db_file = tmp_path / "subdir" / "store.db"

    ensure_sqlite_parent_dir(str(db_file))

    assert db_file.parent.exists()
