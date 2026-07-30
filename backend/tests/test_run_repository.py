"""本模块覆盖运行 仓库的行为、边界与回归场景，确保既有契约稳定。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from deerflow.persistence.run import RunRepository
from deerflow.runtime import CancelOutcome, RunManager, RunStatus
from deerflow.runtime.runs.manager import ConflictError
from deerflow.runtime.runs.store.base import RunStore


async def _make_repo(tmp_path):
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return RunRepository(get_session_factory())


async def _cleanup():
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.persistence.engine import close_engine

    await close_engine()


class _CustomRunStoreWithoutProgress(RunStore):
    """集中覆盖当前测试分支与回归边界。"""
    async def put(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return None

    async def get(self, *args, **kwargs):
        """处理获取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None

    async def list_by_thread(self, *args, **kwargs):
        """处理会话相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return []

    async def update_status(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return None

    async def delete(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return None

    async def update_model_name(self, *args, **kwargs):
        """处理模型相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None

    async def update_run_completion(self, *args, **kwargs):
        """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return None

    async def list_pending(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return []

    async def list_inflight(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return []

    async def aggregate_tokens_by_thread(self, *args, **kwargs):
        """处理会话相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return {}

    async def update_lease(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return True

    async def list_inflight_with_expired_lease(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return []

    async def create_run_atomic(self, *args, **kwargs):
        """处理创建 运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return {}, []

    async def claim_for_takeover(self, *args, **kwargs):
        """准备可控测试资源与状态，供后续断言读取。"""
        return False


@pytest.mark.anyio
async def test_update_run_progress_defaults_to_noop_for_custom_store():
    """验证运行 存储在预期条件及边界场景下的可观察行为，防止相关回归。"""
    store = _CustomRunStoreWithoutProgress()

    await store.update_run_progress("r1", total_tokens=1)


class TestRunRepository:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_put_and_get(self, tmp_path):
        """验证获取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="pending")
        row = await repo.get("r1")
        assert row is not None
        assert row["run_id"] == "r1"
        assert row["thread_id"] == "t1"
        assert row["status"] == "pending"
        await _cleanup()

    @pytest.mark.anyio
    async def test_put_is_idempotent_for_retried_writes(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", assistant_id="old-agent", status="pending")

        await repo.put("r1", thread_id="t1", assistant_id="new-agent", status="running", error="retry")

        row = await repo.get("r1")
        assert row["assistant_id"] == "new-agent"
        assert row["status"] == "running"
        assert row["error"] == "retry"
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_missing_returns_none(self, tmp_path):
        """验证获取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        assert await repo.get("nope") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        updated = await repo.update_status("r1", "running")
        row = await repo.get("r1")
        assert updated is True
        assert row["status"] == "running"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status_returns_false_for_missing_row(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        updated = await repo.update_status("missing", "error", error="lost")
        assert updated is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status_with_error(self, tmp_path):
        """验证错误在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.update_status("r1", "error", error="boom")
        row = await repo.get("r1")
        assert row["status"] == "error"
        assert row["error"] == "boom"
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread(self, tmp_path):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="success")
        await repo.put("r2", thread_id="t1", status="pending")
        await repo.put("r3", thread_id="t2", status="pending")
        rows = await repo.list_by_thread("t1")
        assert len(rows) == 2
        assert all(r["thread_id"] == "t1" for r in rows)
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_owner_filter(self, tmp_path):
        """验证会话 所有者在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", user_id="alice", status="success")
        await repo.put("r2", thread_id="t1", user_id="bob", status="pending")
        rows = await repo.list_by_thread("t1", user_id="alice")
        assert len(rows) == 1
        assert rows[0]["user_id"] == "alice"
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.delete("r1")
        assert await repo.get("r1") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_noop(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        await repo.delete("nope")  # should not raise
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_pending(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="pending")
        await repo.put("r2", thread_id="t2", status="running")
        await repo.put("r3", thread_id="t3", status="pending")
        pending = await repo.list_pending()
        assert len(pending) == 2
        assert all(r["status"] == "pending" for r in pending)
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_inflight_returns_pending_and_running_before_cutoff(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        # Each thread can hold at most one pending/running row (partial unique
        # index ``uq_runs_thread_active``), so spread the inflight rows across
        # distinct threads to exercise the before-cutoff filter.
        await repo.put("pending-old", thread_id="t1", status="pending", created_at="2026-01-01T00:00:00+00:00")
        await repo.put("running-old", thread_id="t2", status="running", created_at="2026-01-01T00:00:01+00:00")
        await repo.put("success-old", thread_id="t3", status="success", created_at="2026-01-01T00:00:02+00:00")
        await repo.put("pending-new", thread_id="t4", status="pending", created_at="2026-01-01T00:00:03+00:00")

        inflight = await repo.list_inflight(before="2026-01-01T00:00:02+00:00")

        assert [row["run_id"] for row in inflight] == ["pending-old", "running-old"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        updated = await repo.update_run_completion(
            "r1",
            status="success",
            total_input_tokens=100,
            total_output_tokens=50,
            total_tokens=150,
            llm_call_count=2,
            lead_agent_tokens=120,
            subagent_tokens=20,
            middleware_tokens=10,
            message_count=3,
            last_ai_message="The answer is 42",
            first_human_message="What is the meaning?",
        )
        row = await repo.get("r1")
        assert updated is True
        assert row["status"] == "success"
        assert row["total_tokens"] == 150
        assert row["llm_call_count"] == 2
        assert row["lead_agent_tokens"] == 120
        assert row["message_count"] == 3
        assert row["last_ai_message"] == "The answer is 42"
        assert row["first_human_message"] == "What is the meaning?"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion_returns_false_for_missing_row(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        updated = await repo.update_run_completion("missing", status="error", total_tokens=1)
        assert updated is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_metadata_preserved(self, tmp_path):
        """验证元数据在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", metadata={"key": "value"})
        row = await repo.get("r1")
        assert row["metadata"] == {"key": "value"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_kwargs_with_non_serializable(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)

        class Dummy:
            """集中覆盖当前测试分支与回归边界。"""
            pass

        await repo.put("r1", thread_id="t1", kwargs={"obj": Dummy()})
        row = await repo.get("r1")
        assert "obj" in row["kwargs"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion_preserves_existing_fields(self, tmp_path):
        """验证运行 已有在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", assistant_id="agent1", status="running")
        await repo.update_run_completion("r1", status="success", total_tokens=100)
        row = await repo.get("r1")
        assert row["thread_id"] == "t1"
        assert row["assistant_id"] == "agent1"
        assert row["total_tokens"] == 100
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_progress_keeps_status_running(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_run_progress(
            "r1",
            total_input_tokens=40,
            total_output_tokens=10,
            total_tokens=50,
            llm_call_count=1,
            message_count=2,
            last_ai_message="partial answer",
        )
        row = await repo.get("r1")
        assert row["status"] == "running"
        assert row["total_tokens"] == 50
        assert row["llm_call_count"] == 1
        assert row["message_count"] == 2
        assert row["last_ai_message"] == "partial answer"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_progress_preserves_omitted_fields(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_run_progress(
            "r1",
            total_input_tokens=40,
            total_output_tokens=10,
            total_tokens=50,
            llm_call_count=1,
            lead_agent_tokens=30,
            subagent_tokens=20,
            message_count=2,
        )

        await repo.update_run_progress("r1", total_tokens=60, last_ai_message="updated")

        row = await repo.get("r1")
        assert row["total_input_tokens"] == 40
        assert row["total_output_tokens"] == 10
        assert row["total_tokens"] == 60
        assert row["llm_call_count"] == 1
        assert row["lead_agent_tokens"] == 30
        assert row["subagent_tokens"] == 20
        assert row["message_count"] == 2
        assert row["last_ai_message"] == "updated"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_progress_skips_terminal_runs(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_run_completion("r1", status="success", total_tokens=100, llm_call_count=1)

        await repo.update_run_progress("r1", total_tokens=200, llm_call_count=2)

        row = await repo.get("r1")
        assert row["status"] == "success"
        assert row["total_tokens"] == 100
        assert row["llm_call_count"] == 1
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_counts_completed_runs_only(self, tmp_path):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("success-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "success-run",
            status="success",
            total_input_tokens=70,
            total_output_tokens=30,
            total_tokens=100,
            lead_agent_tokens=80,
            subagent_tokens=15,
            middleware_tokens=5,
        )
        await repo.put("error-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "error-run",
            status="error",
            total_input_tokens=20,
            total_output_tokens=30,
            total_tokens=50,
            lead_agent_tokens=40,
            subagent_tokens=10,
        )
        await repo.put("running-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "running-run",
            status="running",
            total_input_tokens=900,
            total_output_tokens=99,
            total_tokens=999,
            lead_agent_tokens=999,
        )
        await repo.put("other-thread-run", thread_id="t2", status="running")
        await repo.update_run_completion(
            "other-thread-run",
            status="success",
            total_tokens=888,
            lead_agent_tokens=888,
        )

        agg = await repo.aggregate_tokens_by_thread("t1")

        assert agg["total_tokens"] == 150
        assert agg["total_input_tokens"] == 90
        assert agg["total_output_tokens"] == 60
        assert agg["total_runs"] == 2
        assert agg["by_model"] == {"unknown": {"tokens": 150, "runs": 2}}
        assert agg["by_caller"] == {
            "lead_agent": 120,
            "subagent": 25,
            "middleware": 5,
        }
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_can_include_active_runs(self, tmp_path):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("success-run", thread_id="t1", status="running")
        await repo.update_run_completion("success-run", status="success", total_tokens=100, lead_agent_tokens=100)
        await repo.put("running-run", thread_id="t1", status="running")
        await repo.update_run_progress("running-run", total_tokens=25, lead_agent_tokens=20, subagent_tokens=5)

        without_active = await repo.aggregate_tokens_by_thread("t1")
        with_active = await repo.aggregate_tokens_by_thread("t1", include_active=True)

        assert without_active["total_tokens"] == 100
        assert without_active["total_runs"] == 1
        assert with_active["total_tokens"] == 125
        assert with_active["total_runs"] == 2
        assert with_active["by_caller"] == {
            "lead_agent": 120,
            "subagent": 5,
            "middleware": 0,
        }
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_ordered_desc(self, tmp_path):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="success", created_at="2024-01-01T00:00:00+00:00")
        await repo.put("r2", thread_id="t1", status="pending", created_at="2024-01-02T00:00:00+00:00")
        rows = await repo.list_by_thread("t1")
        assert rows[0]["run_id"] == "r2"
        assert rows[1]["run_id"] == "r1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_limit(self, tmp_path):
        """验证会话 限制在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        # Only one row can be pending/running per thread; mark earlier ones
        # terminal so the partial unique index still holds.
        for i in range(4):
            await repo.put(f"r{i}", thread_id="t1", status="success")
        await repo.put("r4", thread_id="t1", status="pending")
        rows = await repo.list_by_thread("t1", limit=2)
        assert len(rows) == 2
        await _cleanup()

    @pytest.mark.anyio
    async def test_owner_none_returns_all(self, tmp_path):
        """验证所有者在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", user_id="alice", status="success")
        await repo.put("r2", thread_id="t1", user_id="bob", status="pending")
        rows = await repo.list_by_thread("t1", user_id=None)
        assert len(rows) == 2
        await _cleanup()

    @pytest.mark.anyio
    async def test_model_name_persistence(self, tmp_path):
        """验证模型 持久化在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.persistence.engine import get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        repo = RunRepository(get_session_factory())

        await repo.put("run-1", thread_id="thread-1", model_name="gpt-4o", status="success")
        row = await repo.get("run-1")
        assert row is not None
        assert row["model_name"] == "gpt-4o"

        long_name = "a" * 200
        await repo.put("run-2", thread_id="thread-1", model_name=long_name, status="success")
        row2 = await repo.get("run-2")
        assert row2["model_name"] == "a" * 128

        await repo.put("run-3", thread_id="thread-1", model_name=123, status="success")
        row3 = await repo.get("run-3")
        assert row3["model_name"] == "123"

        await repo.put("run-4", thread_id="thread-1", model_name=None, status="pending")
        row4 = await repo.get("run-4")
        assert row4["model_name"] is None

        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_returns_zeros_when_no_rows(self):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        captured = []

        class FakeResult:
            """集中覆盖当前测试分支与回归边界。"""
            def all(self):
                """准备可控测试资源与状态，供后续断言读取。"""
                return []

        class FakeSession:
            """集中覆盖当前测试分支与回归边界。"""
            async def execute(self, stmt):
                """准备可控测试资源与状态，供后续断言读取。"""
                captured.append(stmt)
                return FakeResult()

        class FakeSessionContext:
            """集中覆盖当前测试分支与回归边界。"""
            async def __aenter__(self):
                """准备可控测试资源与状态，供后续断言读取。"""
                return FakeSession()

            async def __aexit__(self, exc_type, exc, tb):
                """准备可控测试资源与状态，供后续断言读取。"""
                return None

        repo = RunRepository(lambda: FakeSessionContext())

        agg = await repo.aggregate_tokens_by_thread("t1")
        assert agg == {
            "total_tokens": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_runs": 0,
            "by_model": {},
            "by_caller": {"lead_agent": 0, "subagent": 0, "middleware": 0},
        }
        assert len(captured) == 1

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_compiles_on_postgres_dialect(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""

        captured = []

        class FakeResult:
            """集中覆盖当前测试分支与回归边界。"""
            def all(self):
                """准备可控测试资源与状态，供后续断言读取。"""
                return []

        class FakeSession:
            """集中覆盖当前测试分支与回归边界。"""
            async def execute(self, stmt):
                """准备可控测试资源与状态，供后续断言读取。"""
                captured.append(stmt)
                return FakeResult()

        class FakeSessionContext:
            """集中覆盖当前测试分支与回归边界。"""
            async def __aenter__(self):
                """准备可控测试资源与状态，供后续断言读取。"""
                return FakeSession()

            async def __aexit__(self, exc_type, exc, tb):
                """准备可控测试资源与状态，供后续断言读取。"""
                return None

        repo = RunRepository(lambda: FakeSessionContext())
        await repo.aggregate_tokens_by_thread("t1")

        compiled = str(captured[0].compile(dialect=postgresql.dialect()))
        assert "token_usage_by_model" in compiled
        assert "GROUP BY" not in compiled.upper()

    @pytest.mark.anyio
    async def test_run_manager_hydrates_store_only_run_from_sql(self, tmp_path):
        """验证运行 管理器 存储 运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put(
            "sql-store-only",
            thread_id="thread-1",
            assistant_id="lead_agent",
            status="success",
            metadata={"source": "sql"},
            kwargs={"input": "value"},
            model_name="model-a",
        )
        manager = RunManager(store=repo)

        record = await manager.get("sql-store-only")
        rows = await manager.list_by_thread("thread-1")

        assert record is not None
        assert record.run_id == "sql-store-only"
        assert record.status == RunStatus.success
        assert record.metadata == {"source": "sql"}
        assert record.kwargs == {"input": "value"}
        assert record.model_name == "model-a"
        assert [run.run_id for run in rows] == ["sql-store-only"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_run_manager_cancel_persists_interrupted_status_to_sql(self, tmp_path):
        """验证运行 管理器在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        manager = RunManager(store=repo)
        record = await manager.create("thread-1")
        await manager.set_status(record.run_id, RunStatus.running)

        cancelled = await manager.cancel(record.run_id)
        row = await repo.get(record.run_id)

        assert cancelled == CancelOutcome.cancelled
        assert row is not None
        assert row["status"] == "interrupted"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_model_name(self, tmp_path):
        """验证模型在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", model_name="initial-model")
        await repo.update_model_name("r1", "updated-model")
        row = await repo.get("r1")
        assert row["model_name"] == "updated-model"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_model_name_normalizes_value(self, tmp_path):
        """验证模型在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        long_name = "a" * 200
        await repo.update_model_name("r1", long_name)
        row = await repo.get("r1")
        assert row["model_name"] == "a" * 128
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_model_name_to_none(self, tmp_path):
        """验证模型在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", model_name="initial-model")
        await repo.update_model_name("r1", None)
        row = await repo.get("r1")
        assert row["model_name"] is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_run_manager_update_model_name_persists_to_sql(self, tmp_path):
        """验证运行 管理器 模型在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        manager = RunManager(store=repo)
        record = await manager.create("thread-1")

        await manager.update_model_name(record.run_id, "gpt-4o")

        row = await repo.get(record.run_id)
        assert row is not None
        assert row["model_name"] == "gpt-4o"
        await _cleanup()

    @pytest.mark.anyio
    async def test_run_manager_update_model_name_twice(self, tmp_path):
        """验证运行 管理器 模型在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        manager = RunManager(store=repo)
        record = await manager.create("thread-1")

        await manager.update_model_name(record.run_id, "model-1")
        await manager.update_model_name(record.run_id, "model-2")

        row = await repo.get(record.run_id)
        assert row["model_name"] == "model-2"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_run_atomic_reject_propagates_conflict_on_unique_violation(self, tmp_path):
        """验证创建 运行 唯一在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from datetime import UTC, datetime, timedelta

        from deerflow.config.run_ownership_config import RunOwnershipConfig

        repo = await _make_repo(tmp_path)
        manager = RunManager(
            store=repo,
            run_ownership_config=RunOwnershipConfig(
                lease_seconds=30,
                grace_seconds=10,
                heartbeat_enabled=False,
            ),
        )

        # Pre-insert an active run on thread T directly through the store so
        # the partial unique index has something to enforce on the second insert.
        lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.create_run_atomic(
            "run-A",
            thread_id="thread-T",
            owner_worker_id="worker-A",
            lease_expires_at=lease,
            multitask_strategy="reject",
            created_at=datetime.now(UTC).isoformat(),
        )

        # Second reject-strategy create against the same thread must convert the
        # underlying IntegrityError into ConflictError via ``_is_unique_violation``.
        with pytest.raises(ConflictError, match="already has an active run"):
            await manager.create_or_reject(
                "thread-T",
                multitask_strategy="reject",
            )

        await _cleanup()

    @pytest.mark.anyio
    async def test_is_unique_violation_detects_real_sqlite_integrity_error(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        import sqlite3

        from sqlalchemy.exc import IntegrityError

        from deerflow.runtime.runs.manager import _is_unique_violation

        repo = await _make_repo(tmp_path)

        # First insert succeeds; second collides on the partial unique index.
        await repo.put("first", thread_id="thread-T", status="pending")
        with pytest.raises(IntegrityError) as exc_info:
            await repo.put("second", thread_id="thread-T", status="pending")

        # The wrapped driver exception must be a sqlite3 IntegrityError carrying
        # SQLITE_CONSTRAINT_UNIQUE. Walk the chain so we assert on the actual
        # driver-level signal, not the SQLAlchemy wrapper.
        driver = exc_info.value.orig
        assert isinstance(driver, sqlite3.IntegrityError)
        assert driver.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE

        # The detector must return True regardless of message phrasing.
        assert _is_unique_violation(exc_info.value) is True

        await _cleanup()

    @pytest.mark.anyio
    async def test_is_unique_violation_does_not_misclassify_application_exception(self):
        """验证唯一在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.runtime.runs.manager import _is_unique_violation

        assert _is_unique_violation(ValueError("duplicate key in input data: 'email'")) is False
        assert _is_unique_violation(RuntimeError("unique violat detected in config")) is False
        assert _is_unique_violation(Exception("unique constraint failed (in a unit test mock)")) is False

    @pytest.mark.anyio
    async def test_is_unique_violation_detects_psycopg3_sqlstate(self):
        """验证唯一在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        from deerflow.runtime.runs.manager import _is_unique_violation

        # Simulate psycopg3's sqlstate attribute on a wrapped IntegrityError
        dbapi_err = Exception()
        dbapi_err.sqlstate = "23505"  # psycopg3 uses sqlstate

        sa_err = SAIntegrityError(
            "duplicate key value violates unique constraint",
            params=None,
            orig=dbapi_err,
        )

        assert _is_unique_violation(sa_err) is True

    @pytest.mark.anyio
    async def test_create_run_atomic_interrupt_tolerates_tz_naive_lease_on_sqlite(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from datetime import UTC, datetime, timedelta

        repo = await _make_repo(tmp_path)

        # Seed an active run owned by another worker with a still-valid lease.
        # The lease value is stored as ISO; SQLite reads it back as a tz-naive
        # datetime — exactly the shape that triggered the bug.
        valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.create_run_atomic(
            "valid-lease-run",
            thread_id="thread-T",
            owner_worker_id="other-worker",
            lease_expires_at=valid_lease,
            multitask_strategy="reject",
            created_at=datetime.now(UTC).isoformat(),
        )

        # The interrupt path must surface a clean ConflictError, not a
        # TypeError from the naive-vs-aware comparison.
        with pytest.raises(ConflictError, match="another worker"):
            await repo.create_run_atomic(
                "run-new",
                thread_id="thread-T",
                owner_worker_id="w1",
                lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                multitask_strategy="interrupt",
                created_at=datetime.now(UTC).isoformat(),
            )

        await _cleanup()

    # ------------------------------------------------------------------
    # claim_for_takeover SQL path
    # ------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_claim_for_takeover_succeeds_with_expired_lease(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        grace = 10
        expired = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
        await repo.put("run-1", thread_id="t1", status="running", owner_worker_id="w-a", lease_expires_at=expired, created_at=datetime.now(UTC).isoformat())

        ok = await repo.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
        assert ok is True

        row = await repo.get("run-1")
        assert row["status"] == "error"
        assert row["error"] == "claimed"
        await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_fails_on_valid_lease(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        grace = 10
        valid = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.put("run-1", thread_id="t1", status="running", owner_worker_id="w-a", lease_expires_at=valid, created_at=datetime.now(UTC).isoformat())

        ok = await repo.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
        assert ok is False

        row = await repo.get("run-1")
        assert row["status"] == "running"
        await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_succeeds_with_null_lease(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        await repo.put("run-null", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

        ok = await repo.claim_for_takeover("run-null", grace_seconds=10, error="claimed")
        assert ok is True

        row = await repo.get("run-null")
        assert row["status"] == "error"
        await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_fails_on_terminal_row(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        repo = await _make_repo(tmp_path)
        await repo.put("run-done", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())

        ok = await repo.claim_for_takeover("run-done", grace_seconds=10, error="claimed")
        assert ok is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_nonexistent_run(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        repo = await _make_repo(tmp_path)
        ok = await repo.claim_for_takeover("no-such-run", grace_seconds=10, error="claimed")
        assert ok is False
        await _cleanup()
