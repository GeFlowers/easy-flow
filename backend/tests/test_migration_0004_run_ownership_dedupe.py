"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import deerflow.persistence.models  # noqa: F401  -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.engine import close_engine, init_engine
from deerflow.persistence.run.model import RunRow

pytestmark = pytest.mark.asyncio


def _seed_pre_0004_with_duplicates(db_path: Path) -> None:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            conn.execute(sa.text("DROP INDEX IF EXISTS uq_runs_thread_active"))
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0003_scheduled_tasks')"))

        base = datetime.now(UTC)
        with Session(sync_engine) as session:
            session.add_all(
                [
                    RunRow(
                        run_id="run-old-a",
                        thread_id="thread-dup",
                        status="pending",
                        created_at=base,
                        updated_at=base,
                    ),
                    RunRow(
                        run_id="run-old-b",
                        thread_id="thread-dup",
                        status="running",
                        created_at=base + timedelta(seconds=10),
                        updated_at=base + timedelta(seconds=10),
                    ),
                    RunRow(
                        run_id="run-newest",
                        thread_id="thread-dup",
                        status="pending",
                        created_at=base + timedelta(seconds=60),
                        updated_at=base + timedelta(seconds=60),
                    ),
                    RunRow(
                        run_id="run-solo",
                        thread_id="thread-solo",
                        status="running",
                        created_at=base,
                        updated_at=base,
                    ),
                    RunRow(
                        run_id="run-success",
                        thread_id="thread-done",
                        status="success",
                        created_at=base,
                        updated_at=base,
                    ),
                ]
            )
            session.commit()
    finally:
        sync_engine.dispose()


def _fetch_runs(db_path: Path) -> dict[str, tuple[str, str | None]]:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    with sqlite3.connect(db_path) as raw:
        rows = raw.execute("SELECT run_id, status, error FROM runs").fetchall()
    return {run_id: (status, error) for run_id, status, error in rows}


def _index_exists(db_path: Path, index_name: str) -> bool:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    with sqlite3.connect(db_path) as raw:
        row = raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        ).fetchone()
    return row is not None


async def test_migration_dedupes_duplicate_active_rows_before_unique_index(tmp_path: Path) -> None:
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    db_path = tmp_path / "dirty.db"
    _seed_pre_0004_with_duplicates(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))

    try:
        runs = _fetch_runs(db_path)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert runs["run-newest"] == ("pending", None)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert runs["run-old-a"][0] == "error"
        assert "uq_runs_thread_active" in (runs["run-old-a"][1] or "")
        assert runs["run-old-b"][0] == "error"
        assert "uq_runs_thread_active" in (runs["run-old-b"][1] or "")

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert runs["run-solo"] == ("running", None)
        assert runs["run-success"] == ("success", None)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert _index_exists(db_path, "uq_runs_thread_active")
        assert _index_exists(db_path, "ix_runs_lease")

        with sqlite3.connect(db_path) as raw:
            version_row = raw.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version_row[0] == "0005_run_stop_reason"

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        with sqlite3.connect(db_path) as raw:
            dupes = raw.execute("SELECT thread_id, COUNT(*) FROM runs WHERE status IN ('pending', 'running') GROUP BY thread_id HAVING COUNT(*) > 1").fetchall()
        assert dupes == []
    finally:
        await close_engine()
