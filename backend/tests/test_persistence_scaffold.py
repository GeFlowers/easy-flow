"""本模块覆盖持久化的行为、边界与回归场景，确保既有契约稳定。"""

import sys
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.runtime.runs.store.memory import MemoryRunStore

# -- DatabaseConfig --


class TestDatabaseConfig:
    """集中覆盖当前测试分支与回归边界。"""
    def test_defaults(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        c = DatabaseConfig()
        assert c.backend == "memory"
        assert c.pool_size == 5

    def test_sqlite_paths_unified(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        c = DatabaseConfig(backend="sqlite", sqlite_dir="./mydata")
        assert c.sqlite_path.endswith("deerflow.db")
        assert "mydata" in c.sqlite_path
        # Backward-compatible aliases point to the same file
        assert c.checkpointer_sqlite_path == c.sqlite_path
        assert c.app_sqlite_path == c.sqlite_path

    def test_app_sqlalchemy_url_sqlite(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        c = DatabaseConfig(backend="sqlite", sqlite_dir="./data")
        url = c.app_sqlalchemy_url
        assert url.startswith("sqlite+aiosqlite:///")
        assert "deerflow.db" in url

    def test_app_sqlalchemy_url_postgres(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        c = DatabaseConfig(
            backend="postgres",
            postgres_url="postgresql://u:p@h:5432/db",
        )
        url = c.app_sqlalchemy_url
        assert url.startswith("postgresql+asyncpg://")
        assert "u:p@h:5432/db" in url

    def test_app_sqlalchemy_url_postgres_already_asyncpg(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        c = DatabaseConfig(
            backend="postgres",
            postgres_url="postgresql+asyncpg://u:p@h:5432/db",
        )
        url = c.app_sqlalchemy_url
        assert url.count("asyncpg") == 1

    def test_memory_has_no_url(self):
        """验证内存在预期条件及边界场景下的可观察行为，防止相关回归。"""
        c = DatabaseConfig(backend="memory")
        with pytest.raises(ValueError, match="No SQLAlchemy URL"):
            _ = c.app_sqlalchemy_url


# -- MemoryRunStore --


class TestMemoryRunStore:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.fixture
    def store(self):
        """为存储准备隔离的测试依赖，并由夹具作用域管理其生命周期。"""
        return MemoryRunStore()

    @pytest.mark.anyio
    async def test_put_and_get(self, store):
        """验证获取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1", status="pending")
        row = await store.get("r1")
        assert row is not None
        assert row["run_id"] == "r1"
        assert row["status"] == "pending"

    @pytest.mark.anyio
    async def test_get_missing_returns_none(self, store):
        """验证获取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert await store.get("nope") is None

    @pytest.mark.anyio
    async def test_update_status(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        await store.put("r1", thread_id="t1")
        await store.update_status("r1", "running")
        assert (await store.get("r1"))["status"] == "running"

    @pytest.mark.anyio
    async def test_update_status_with_error(self, store):
        """验证错误在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1")
        await store.update_status("r1", "error", error="boom")
        row = await store.get("r1")
        assert row["status"] == "error"
        assert row["error"] == "boom"

    @pytest.mark.anyio
    async def test_list_by_thread(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1")
        await store.put("r2", thread_id="t1")
        await store.put("r3", thread_id="t2")
        rows = await store.list_by_thread("t1")
        assert len(rows) == 2
        assert all(r["thread_id"] == "t1" for r in rows)

    @pytest.mark.anyio
    async def test_list_by_thread_owner_filter(self, store):
        """验证会话 所有者在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1", user_id="alice")
        await store.put("r2", thread_id="t1", user_id="bob")
        rows = await store.list_by_thread("t1", user_id="alice")
        assert len(rows) == 1
        assert rows[0]["user_id"] == "alice"

    @pytest.mark.anyio
    async def test_owner_none_returns_all(self, store):
        """验证所有者在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1", user_id="alice")
        await store.put("r2", thread_id="t1", user_id="bob")
        rows = await store.list_by_thread("t1", user_id=None)
        assert len(rows) == 2

    @pytest.mark.anyio
    async def test_delete(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        await store.put("r1", thread_id="t1")
        await store.delete("r1")
        assert await store.get("r1") is None

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_noop(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        await store.delete("nope")  # should not raise

    @pytest.mark.anyio
    async def test_list_by_thread_unknown_thread_is_empty(self, store):
        """验证会话 会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1")
        assert await store.list_by_thread("missing") == []

    @pytest.mark.anyio
    async def test_list_by_thread_newest_first(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1", created_at="2024-01-01T00:00:00+00:00")
        await store.put("r2", thread_id="t1", created_at="2024-01-03T00:00:00+00:00")
        await store.put("r3", thread_id="t1", created_at="2024-01-02T00:00:00+00:00")
        rows = await store.list_by_thread("t1")
        assert [r["run_id"] for r in rows] == ["r2", "r3", "r1"]

    @pytest.mark.anyio
    async def test_list_by_thread_respects_limit(self, store):
        """验证会话 限制在预期条件及边界场景下的可观察行为，防止相关回归。"""
        for i in range(5):
            await store.put(f"r{i}", thread_id="t1", created_at=f"2024-01-0{i + 1}T00:00:00+00:00")
        rows = await store.list_by_thread("t1", limit=2)
        assert [r["run_id"] for r in rows] == ["r4", "r3"]

    @pytest.mark.anyio
    async def test_delete_keeps_thread_index_consistent(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1")
        await store.put("r2", thread_id="t1")
        await store.delete("r1")
        rows = await store.list_by_thread("t1")
        assert [r["run_id"] for r in rows] == ["r2"]
        # deleting the last run in a thread drops the now-empty index bucket
        await store.delete("r2")
        assert await store.list_by_thread("t1") == []
        assert "t1" not in store._runs_by_thread

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_scopes_to_thread(self, store):
        """验证会话 会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1")
        await store.update_run_completion("r1", status="success", model_name="m-a", total_tokens=100)
        await store.put("r2", thread_id="t1")
        await store.update_run_completion("r2", status="error", model_name="m-a", total_tokens=20)
        await store.put("r3", thread_id="t2")
        await store.update_run_completion("r3", status="success", model_name="m-b", total_tokens=999)

        agg = await store.aggregate_tokens_by_thread("t1")
        assert agg["total_tokens"] == 120  # the other thread's run is excluded
        assert agg["total_runs"] == 2
        assert agg["by_model"]["m-a"] == {"tokens": 120, "runs": 2}
        assert "m-b" not in agg["by_model"]

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_excludes_active_unless_requested(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1")
        await store.update_run_completion("r1", status="success", total_tokens=10)
        await store.put("r2", thread_id="t1")
        await store.update_run_completion("r2", status="running", total_tokens=5)

        assert (await store.aggregate_tokens_by_thread("t1"))["total_tokens"] == 10
        assert (await store.aggregate_tokens_by_thread("t1", include_active=True))["total_tokens"] == 15

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_unknown_thread_is_zero(self, store):
        """验证会话 会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put("r1", thread_id="t1")
        await store.update_run_completion("r1", status="success", total_tokens=10)
        agg = await store.aggregate_tokens_by_thread("missing")
        assert agg["total_tokens"] == 0
        assert agg["total_runs"] == 0
        assert agg["by_model"] == {}

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_matches_full_scan_reference(self, store):
        """验证会话 扫描在预期条件及边界场景下的可观察行为，防止相关回归。"""
        plan = [
            ("r0", "t1", "success", "m-a", 10),
            ("r1", "t1", "error", "m-b", 20),
            ("r2", "t1", "running", "m-a", 7),
            ("r3", "t2", "success", "m-a", 999),
            ("r4", "t1", "pending", "m-a", 3),
        ]
        for run_id, thread_id, status, model, tokens in plan:
            await store.put(run_id, thread_id=thread_id)
            await store.update_run_completion(run_id, status=status, model_name=model, total_tokens=tokens)

        def _reference(thread_id, include_active):
            """准备可控测试资源与状态，供后续断言读取。"""
            statuses = ("success", "error", "running") if include_active else ("success", "error")
            completed = [r for r in store._runs.values() if r["thread_id"] == thread_id and r.get("status") in statuses]
            return len(completed), sum(r.get("total_tokens", 0) for r in completed)

        for thread_id in ("t1", "t2", "missing"):
            for include_active in (False, True):
                agg = await store.aggregate_tokens_by_thread(thread_id, include_active=include_active)
                ref_runs, ref_tokens = _reference(thread_id, include_active)
                assert (agg["total_runs"], agg["total_tokens"]) == (ref_runs, ref_tokens), (thread_id, include_active)

    @pytest.mark.anyio
    async def test_list_pending(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        await store.put("r1", thread_id="t1", status="pending")
        await store.put("r2", thread_id="t1", status="running")
        await store.put("r3", thread_id="t2", status="pending")
        pending = await store.list_pending()
        assert len(pending) == 2
        assert all(r["status"] == "pending" for r in pending)

    @pytest.mark.anyio
    async def test_list_pending_respects_before(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        past = "2020-01-01T00:00:00+00:00"
        future = "2099-01-01T00:00:00+00:00"
        await store.put("r1", thread_id="t1", status="pending", created_at=past)
        await store.put("r2", thread_id="t1", status="pending", created_at=future)
        pending = await store.list_pending(before=datetime.now(UTC).isoformat())
        assert len(pending) == 1
        assert pending[0]["run_id"] == "r1"

    @pytest.mark.anyio
    async def test_list_pending_fifo_order(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        await store.put("r2", thread_id="t1", status="pending", created_at="2024-01-02T00:00:00+00:00")
        await store.put("r1", thread_id="t1", status="pending", created_at="2024-01-01T00:00:00+00:00")
        pending = await store.list_pending()
        assert pending[0]["run_id"] == "r1"


# -- Base.to_dict mixin --


class TestBaseToDictMixin:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_to_dict_and_exclude(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from sqlalchemy import String
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.orm import Mapped, mapped_column

        from deerflow.persistence.base import Base

        class _Tmp(Base):
            """集中覆盖当前测试分支与回归边界。"""
            __tablename__ = "_tmp_test"
            id: Mapped[str] = mapped_column(String(64), primary_key=True)
            name: Mapped[str] = mapped_column(String(128))

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as session:
            session.add(_Tmp(id="1", name="hello"))
            await session.commit()
            obj = await session.get(_Tmp, "1")

            assert obj.to_dict() == {"id": "1", "name": "hello"}
            assert obj.to_dict(exclude={"name"}) == {"id": "1"}
            assert "_Tmp" in repr(obj)

        await engine.dispose()


# -- Engine lifecycle --


class TestEngineLifecycle:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_memory_is_noop(self):
        """验证内存在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        await init_engine("memory")
        assert get_session_factory() is None
        await close_engine()

    @pytest.mark.anyio
    async def test_sqlite_creates_engine(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        sf = get_session_factory()
        assert sf is not None
        async with sf() as session:
            assert session is not None
        await close_engine()
        assert get_session_factory() is None

    @pytest.mark.anyio
    async def test_postgres_without_asyncpg_gives_actionable_error(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.persistence.engine import init_engine

        with (
            patch.dict(sys.modules, {"asyncpg": None}),
            pytest.raises(ImportError, match="uv sync --all-packages --extra postgres"),
        ):
            await init_engine("postgres", url="postgresql+asyncpg://x:x@localhost/x")
