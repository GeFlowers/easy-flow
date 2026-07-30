"""本模块覆盖相关测试，固定公开行为、失败处理与状态边界。"""

from __future__ import annotations

import asyncio

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.runtime import CancelOutcome, RunManager, RunStatus

THREAD_ID = "thread-cancel-test"


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------


def _make_app(mgr: RunManager) -> TestClient:
    """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_manager = mgr
    return TestClient(app, raise_server_exceptions=False)


def _create_interrupted_run(mgr: RunManager) -> str:
    """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""

    async def _setup():
        """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
        record = await mgr.create(THREAD_ID)
        await mgr.set_status(record.run_id, RunStatus.running)
        await mgr.cancel(record.run_id)
        return record.run_id

    return asyncio.run(_setup())


# ---------------------------------------------------------------------------
# 此处说明该测试段的前置条件、调用限制及预期边界。
# ---------------------------------------------------------------------------


class TestRunManagerCancelIdempotency:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_cancel_returns_cancelled_for_already_interrupted_run(self):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过2项断言固定返回、状态或副作用边界。"""

        async def run():
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            mgr = RunManager()
            record = await mgr.create(THREAD_ID)
            await mgr.set_status(record.run_id, RunStatus.running)
            first = await mgr.cancel(record.run_id)
            assert first == CancelOutcome.cancelled
            second = await mgr.cancel(record.run_id)
            assert second == CancelOutcome.cancelled  # 此处说明该测试段的前置条件、调用限制及预期边界。

        asyncio.run(run())

    def test_cancel_returns_not_cancellable_for_successful_run(self):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""

        async def run():
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            mgr = RunManager()
            record = await mgr.create(THREAD_ID)
            await mgr.set_status(record.run_id, RunStatus.running)
            await mgr.set_status(record.run_id, RunStatus.success)
            result = await mgr.cancel(record.run_id)
            assert result == CancelOutcome.not_cancellable

        asyncio.run(run())

    def test_cancel_returns_not_active_locally_for_unknown_run(self):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        async def run():
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            mgr = RunManager()
            result = await mgr.cancel("nonexistent-run-id")
            assert result == CancelOutcome.not_active_locally

        asyncio.run(run())


# ---------------------------------------------------------------------------
# 此处说明该测试段的前置条件、调用限制及预期边界。
# ---------------------------------------------------------------------------


class TestCancelRunEndpointIdempotency:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_double_cancel_returns_202_not_409(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        mgr = RunManager()
        run_id = _create_interrupted_run(mgr)
        client = _make_app(mgr)

        resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"

    def test_cancel_unknown_run_returns_404(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        mgr = RunManager()
        client = _make_app(mgr)
        resp = client.post(f"/api/threads/{THREAD_ID}/runs/no-such-run/cancel")
        assert resp.status_code == 404

    def test_cancel_successful_run_returns_409(self):
        """验证当前场景的异步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""

        async def _setup():
            """准备隔离的测试前置条件，避免真实外部依赖影响后续断言。"""
            mgr = RunManager()
            record = await mgr.create(THREAD_ID)
            await mgr.set_status(record.run_id, RunStatus.running)
            await mgr.set_status(record.run_id, RunStatus.success)
            return mgr, record.run_id

        mgr, run_id = asyncio.run(_setup())
        client = _make_app(mgr)
        resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 此处说明该测试段的前置条件、调用限制及预期边界。
# ---------------------------------------------------------------------------


class TestStreamExistingRunIdempotentCancel:
    """此测试组归集同一组件的用例，分别约束正常流程与关键边界条件。"""
    def test_stream_cancel_already_interrupted_returns_not_409(self):
        """验证当前场景的同步调用：使用受控输入与依赖替身，通过1项断言固定返回、状态或副作用边界。"""
        mgr = RunManager()
        run_id = _create_interrupted_run(mgr)
        client = _make_app(mgr)

        resp = client.post(
            f"/api/threads/{THREAD_ID}/runs/{run_id}/join",
            params={"action": "interrupt"},
        )
        assert resp.status_code != 409, f"Should not 409 on idempotent cancel, got {resp.status_code}"
