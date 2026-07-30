"""本模块覆盖持久化 脚本的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence.base import Base


@pytest.fixture(scope="module")
def autogen_module():
    """准备可控测试资源与状态，供后续断言读取。"""
    script_path = Path(__file__).resolve().parents[1] / "scripts/_autogen_revision.py"
    assert script_path.exists(), f"missing autogen script at {script_path}"
    spec = importlib.util.spec_from_file_location("_autogen_revision_under_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_autogen_builds_temp_db_at_head_without_data_dir(autogen_module, monkeypatch) -> None:
    """验证数据在预期条件及边界场景下的可观察行为，防止相关回归。"""
    import os  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    workdir = tempfile.mkdtemp(prefix="deerflow-autogen-test-")
    monkeypatch.chdir(workdir)
    # Sanity: this directory has no ``./data/`` -- so the alembic.ini default
    # URL would fail if used.
    assert not os.path.exists("data")

    url = autogen_module._build_temp_db_at_head()
    assert url.startswith("sqlite+aiosqlite:///"), f"unexpected URL shape: {url}"
    # The temp DB file should now exist.
    db_path = url.replace("sqlite+aiosqlite:///", "")
    assert os.path.exists(db_path), f"temp DB file not created at {db_path}"


def test_autogen_temp_db_is_at_head(autogen_module) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    import sqlite3  # noqa: PLC0415

    url = autogen_module._build_temp_db_at_head()
    db_path = url.replace("sqlite+aiosqlite:///", "")
    with sqlite3.connect(db_path) as raw:
        row = raw.execute("SELECT version_num FROM alembic_version").fetchone()
        assert row is not None, "autogen temp DB has no alembic_version row -- bootstrap failed"
        # head is whatever the script tree currently says; we just assert it's there.
        assert row[0]


def test_autogen_temp_db_comes_from_migration_history_not_current_metadata(autogen_module) -> None:
    """验证迁移 元数据在预期条件及边界场景下的可观察行为，防止相关回归。"""
    import sqlite3  # noqa: PLC0415

    probe_name = "__autogen_probe_pending_migration__"
    probe_table = sa.Table(probe_name, Base.metadata, sa.Column("id", sa.Integer, primary_key=True))
    try:
        url = autogen_module._build_temp_db_at_head()
        db_path = url.replace("sqlite+aiosqlite:///", "")
        with sqlite3.connect(db_path) as raw:
            exists = raw.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
                (probe_name,),
            ).fetchone()[0]
        assert exists == 0, "temp DB was built from current ORM metadata instead of migration history"
    finally:
        Base.metadata.remove(probe_table)
