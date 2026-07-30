"""本模块覆盖持久化的行为、边界与回归场景，确保既有契约稳定。"""

import re

import pytest

_TZ_SUFFIX_RE = re.compile(r"(?:\+\d{2}:\d{2}|Z)$")


def _assert_tz_aware(value: str | None, *, context: str) -> None:
    """准备可控测试资源与状态，供后续断言读取。"""
    assert value, f"{context}: expected ISO string, got {value!r}"
    assert _TZ_SUFFIX_RE.search(value), f"{context}: timestamp lacks tz suffix: {value!r}"


async def _init_sqlite(tmp_path):
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'tz.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return get_session_factory()


async def _cleanup():
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.persistence.engine import close_engine

    await close_engine()


@pytest.mark.anyio
async def test_thread_meta_emits_tz_aware_timestamps(tmp_path):
    """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    repo = ThreadMetaRepository(await _init_sqlite(tmp_path))
    try:
        created = await repo.create("t-tz", user_id="u1", display_name="tz")
        _assert_tz_aware(created["created_at"], context="thread_meta.create.created_at")
        _assert_tz_aware(created["updated_at"], context="thread_meta.create.updated_at")

        # Second read from DB exercises the same _row_to_dict path on a
        # value that SQLite has round-tripped (where tzinfo is lost).
        fetched = await repo.get("t-tz", user_id="u1")
        _assert_tz_aware(fetched["created_at"], context="thread_meta.get.created_at")
        _assert_tz_aware(fetched["updated_at"], context="thread_meta.get.updated_at")

        listed = await repo.search(user_id="u1")
        assert listed, "search must return the created row"
        _assert_tz_aware(listed[0]["created_at"], context="thread_meta.search.created_at")
        _assert_tz_aware(listed[0]["updated_at"], context="thread_meta.search.updated_at")
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_run_repository_emits_tz_aware_timestamps(tmp_path):
    """验证运行 仓库在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.persistence.run import RunRepository

    repo = RunRepository(await _init_sqlite(tmp_path))
    try:
        await repo.put("r-tz", thread_id="t-tz", user_id="u1")
        row = await repo.get("r-tz", user_id="u1")
        _assert_tz_aware(row["created_at"], context="run.get.created_at")
        _assert_tz_aware(row["updated_at"], context="run.get.updated_at")
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_feedback_repository_emits_tz_aware_timestamps(tmp_path):
    """验证仓库在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.persistence.feedback import FeedbackRepository

    repo = FeedbackRepository(await _init_sqlite(tmp_path))
    try:
        record = await repo.create(run_id="r-tz", thread_id="t-tz", rating=1, user_id="u1")
        _assert_tz_aware(record["created_at"], context="feedback.create.created_at")
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_run_event_store_emits_tz_aware_timestamps(tmp_path):
    """验证运行 事件 存储在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.runtime.events.store.db import DbRunEventStore

    store = DbRunEventStore(await _init_sqlite(tmp_path))
    try:
        await store.put(
            thread_id="t-tz",
            run_id="r-tz",
            event_type="log",
            category="log",
            content="hello",
        )
        events = await store.list_events("t-tz", "r-tz", user_id=None)
        assert events, "expected at least one event"
        _assert_tz_aware(events[0]["created_at"], context="run_event.list.created_at")
    finally:
        await _cleanup()
