"""验证持久化仓储及运行事件在不同用户上下文之间的所有者隔离。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.runtime.user_context import (
    reset_current_user,
    set_current_user,
)

USER_A = SimpleNamespace(id="user-a", email="a@test.local")
USER_B = SimpleNamespace(id="user-b", email="b@test.local")


async def _make_engines(tmp_path):
    """初始化临时 SQLite 引擎，并返回供各测试 finally 块调用的关闭协程。"""
    from deerflow.persistence.engine import close_engine, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'isolation.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return close_engine


def _as_user(user):
    """返回在上下文进入和退出时设置、重置当前用户的上下文管理器。"""

    class _Ctx:
        """封装单次用户上下文切换，确保 token 在退出时恢复。"""
        def __enter__(self):
            """写入当前用户并保存 ContextVar token，供退出时重置。"""
            self._token = set_current_user(user)
            return user

        def __exit__(self, *exc):
            """使用进入时保存的 token 恢复此前的用户上下文。"""
            reset_current_user(self._token)

    return _Ctx()


# ── TC-API-17：线程元数据隔离 ───────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_thread_meta_cross_user_isolation(tmp_path):
    """验证线程元数据的读取与搜索均只返回当前用户创建的线程。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())

        # 用户 A 创建线程。
        with _as_user(USER_A):
            await repo.create("t-alpha", display_name="A's private thread")

        # 用户 B 创建线程。
        with _as_user(USER_B):
            await repo.create("t-beta", display_name="B's private thread")

        # 用户 A 只能看到自己的线程。
        with _as_user(USER_A):
            a_view = await repo.get("t-alpha")
            assert a_view is not None
            assert a_view["display_name"] == "A's private thread"

            # 关键边界：用户 A 绝不能看到用户 B 的线程。
            leaked = await repo.get("t-beta")
            assert leaked is None, f"User A leaked User B's thread: {leaked}"

            # 搜索结果也只能包含用户 A 的线程。
            results = await repo.search()
            assert [r["thread_id"] for r in results] == ["t-alpha"]

        # 用户 B 只能看到自己的线程。
        with _as_user(USER_B):
            b_view = await repo.get("t-beta")
            assert b_view is not None
            assert b_view["display_name"] == "B's private thread"

            leaked = await repo.get("t-alpha")
            assert leaked is None, f"User B leaked User A's thread: {leaked}"

            results = await repo.search()
            assert [r["thread_id"] for r in results] == ["t-beta"]
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_thread_meta_cross_user_mutation_denied(tmp_path):
    """验证非所有者更新或删除线程元数据不会改变原记录。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())

        with _as_user(USER_A):
            await repo.create("t-alpha", display_name="original")

        # 用户 B 尝试重命名用户 A 的线程，操作必须无副作用。
        with _as_user(USER_B):
            await repo.update_display_name("t-alpha", "hacked")

        # 从用户 A 的视角确认记录未改变。
        with _as_user(USER_A):
            row = await repo.get("t-alpha")
            assert row is not None
            assert row["display_name"] == "original"

        # 用户 B 尝试删除用户 A 的线程，操作必须无副作用。
        with _as_user(USER_B):
            await repo.delete("t-alpha")

        # 用户 A 的线程仍然存在。
        with _as_user(USER_A):
            row = await repo.get("t-alpha")
            assert row is not None
    finally:
        await cleanup()


# ── TC-API-18：运行记录隔离 ─────────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_runs_cross_user_isolation(tmp_path):
    """验证运行记录的按标识读取和按线程列举均受当前用户过滤。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.run import RunRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = RunRepository(get_session_factory())

        with _as_user(USER_A):
            await repo.put("run-a1", thread_id="t-alpha", status="success")
            await repo.put("run-a2", thread_id="t-alpha", status="pending")

        with _as_user(USER_B):
            await repo.put("run-b1", thread_id="t-beta")

        # 用户 A 只能看到自己的运行记录。
        with _as_user(USER_A):
            r = await repo.get("run-a1")
            assert r is not None
            assert r["run_id"] == "run-a1"

            leaked = await repo.get("run-b1")
            assert leaked is None, "User A leaked User B's run"

            a_runs = await repo.list_by_thread("t-alpha")
            assert {r["run_id"] for r in a_runs} == {"run-a1", "run-a2"}

            # 用户 A 列举用户 B 的线程时应得到空列表。
            empty = await repo.list_by_thread("t-beta")
            assert empty == []

        # 用户 B 只能看到自己的运行记录。
        with _as_user(USER_B):
            leaked = await repo.get("run-a1")
            assert leaked is None, "User B leaked User A's run"

            b_runs = await repo.list_by_thread("t-beta")
            assert [r["run_id"] for r in b_runs] == ["run-b1"]
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_runs_cross_user_delete_denied(tmp_path):
    """验证非所有者删除运行记录时无副作用，原记录仍可由所有者读取。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.run import RunRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = RunRepository(get_session_factory())

        with _as_user(USER_A):
            await repo.put("run-a1", thread_id="t-alpha")

        # 用户 B 尝试删除用户 A 的运行记录，操作无副作用。
        with _as_user(USER_B):
            await repo.delete("run-a1")

        # 用户 A 的运行记录仍然存在。
        with _as_user(USER_A):
            row = await repo.get("run-a1")
            assert row is not None
    finally:
        await cleanup()


# ── TC-API-19：运行事件隔离（关键：防止内容泄露） ────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_run_events_cross_user_isolation(tmp_path):
    """验证运行事件的消息、事件和计数接口均不会泄露其他用户内容。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.runtime.events.store.db import DbRunEventStore

    cleanup = await _make_engines(tmp_path)
    try:
        store = DbRunEventStore(get_session_factory())

        with _as_user(USER_A):
            await store.put(
                thread_id="t-alpha",
                run_id="run-a1",
                event_type="human_message",
                category="message",
                content="User A private question",
            )
            await store.put(
                thread_id="t-alpha",
                run_id="run-a1",
                event_type="ai_message",
                category="message",
                content="User A private answer",
            )

        with _as_user(USER_B):
            await store.put(
                thread_id="t-beta",
                run_id="run-b1",
                event_type="human_message",
                category="message",
                content="User B private question",
            )

        # 关键边界：用户 A 只能看到自己的事件。
        with _as_user(USER_A):
            msgs = await store.list_messages("t-alpha")
            contents = [m["content"] for m in msgs]
            assert "User A private question" in contents
            assert "User A private answer" in contents
            # 关键边界：结果中不得出现用户 B 的内容。
            assert "User B private question" not in contents

            # 即使猜中用户 B 的 thread_id，也不能读取其消息。
            leaked = await store.list_messages("t-beta")
            assert leaked == [], f"User A leaked User B's messages: {leaked}"

            leaked_events = await store.list_events("t-beta", "run-b1")
            assert leaked_events == [], "User A leaked User B's events"

            # 从用户 A 的视角，用户 B 线程的消息数也必须为零。
            count = await store.count_messages("t-beta")
            assert count == 0

        # 用户 B 只能看到自己的事件。
        with _as_user(USER_B):
            msgs = await store.list_messages("t-beta")
            contents = [m["content"] for m in msgs]
            assert "User B private question" in contents
            assert "User A private question" not in contents
            assert "User A private answer" not in contents

            count = await store.count_messages("t-alpha")
            assert count == 0
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_run_events_cross_user_delete_denied(tmp_path):
    """验证非所有者无法清空他人线程的运行事件，删除数量为零。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.runtime.events.store.db import DbRunEventStore

    cleanup = await _make_engines(tmp_path)
    try:
        store = DbRunEventStore(get_session_factory())

        with _as_user(USER_A):
            await store.put(
                thread_id="t-alpha",
                run_id="run-a1",
                event_type="human_message",
                category="message",
                content="hello",
            )

        # 用户 B 尝试清空用户 A 线程的事件。
        with _as_user(USER_B):
            removed = await store.delete_by_thread("t-alpha")
            assert removed == 0, f"User B deleted {removed} of User A's events"

        # 用户 A 的事件仍然存在。
        with _as_user(USER_A):
            count = await store.count_messages("t-alpha")
            assert count == 1
    finally:
        await cleanup()


# ── TC-API-20：反馈隔离 ─────────────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_feedback_cross_user_isolation(tmp_path):
    """验证反馈按标识和按运行读取时不会跨用户泄露。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.feedback import FeedbackRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = FeedbackRepository(get_session_factory())

        # 用户 A 提交正向反馈。
        with _as_user(USER_A):
            a_feedback = await repo.create(
                run_id="run-a1",
                thread_id="t-alpha",
                rating=1,
                comment="A liked this",
            )

        # 用户 B 提交负向反馈。
        with _as_user(USER_B):
            b_feedback = await repo.create(
                run_id="run-b1",
                thread_id="t-beta",
                rating=-1,
                comment="B disliked this",
            )

        # 用户 A 只能看到自己的反馈。
        with _as_user(USER_A):
            retrieved = await repo.get(a_feedback["feedback_id"])
            assert retrieved is not None
            assert retrieved["comment"] == "A liked this"

            # 关键边界：不能通过标识读取用户 B 的反馈。
            leaked = await repo.get(b_feedback["feedback_id"])
            assert leaked is None, "User A leaked User B's feedback"

            # 查询用户 B 运行的反馈列表必须为空。
            empty = await repo.list_by_run("t-beta", "run-b1")
            assert empty == []

        # 用户 B 只能看到自己的反馈。
        with _as_user(USER_B):
            leaked = await repo.get(a_feedback["feedback_id"])
            assert leaked is None, "User B leaked User A's feedback"

            b_list = await repo.list_by_run("t-beta", "run-b1")
            assert len(b_list) == 1
            assert b_list[0]["comment"] == "B disliked this"
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_feedback_cross_user_delete_denied(tmp_path):
    """验证非所有者删除反馈会返回 False，且反馈仍可由所有者读取。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.feedback import FeedbackRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = FeedbackRepository(get_session_factory())

        with _as_user(USER_A):
            fb = await repo.create(run_id="run-a1", thread_id="t-alpha", rating=1)

        # 用户 B 尝试删除用户 A 的反馈，必须返回 False 且无副作用。
        with _as_user(USER_B):
            deleted = await repo.delete(fb["feedback_id"])
            assert deleted is False, "User B deleted User A's feedback"

        # 用户 A 的反馈仍可读取。
        with _as_user(USER_A):
            row = await repo.get(fb["feedback_id"])
            assert row is not None
    finally:
        await cleanup()


# ── 回归边界：缺少 ContextVar 时 AUTO 哨兵必须报错 ───────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_repository_without_context_raises(tmp_path):
    """验证 no_auto_user 夹具清除用户上下文后，AUTO 查询会抛出 RuntimeError。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())
        # @pytest.mark.no_auto_user 会显式清除 ContextVar。
        with pytest.raises(RuntimeError, match="no user context is set"):
            await repo.get("anything")
    finally:
        await cleanup()


# ── 迁移逃生口：显式 user_id=None 绕过所有者过滤 ────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_explicit_none_bypasses_filter(tmp_path):
    """验证迁移场景显式传入 user_id=None 时可跨所有者读取全部线程。"""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())

        # 以两个不同用户身份写入种子数据。
        with _as_user(USER_A):
            await repo.create("t-alpha")
        with _as_user(USER_B):
            await repo.create("t-beta")

        # 模拟迁移读取：没有用户上下文，显式 None 绕过过滤。
        all_rows = await repo.search(user_id=None)
        thread_ids = {r["thread_id"] for r in all_rows}
        assert thread_ids == {"t-alpha", "t-beta"}

        # 显式传入 None 的单条读取同样不应用过滤。
        row_a = await repo.get("t-alpha", user_id=None)
        assert row_a is not None
        row_b = await repo.get("t-beta", user_id=None)
        assert row_b is not None
    finally:
        await cleanup()
