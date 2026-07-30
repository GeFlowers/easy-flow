"""本模块覆盖接口的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from _run_message_pagination_helpers import assert_run_message_page
from fastapi.testclient import TestClient

from app.gateway.routers import runs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(run_store=None, event_store=None, feedback_repo=None):
    """准备可控测试资源与状态，供后续断言读取。"""
    app = make_authed_test_app()
    app.include_router(runs.router)

    if run_store is not None:
        app.state.run_store = run_store
    if event_store is not None:
        app.state.run_event_store = event_store
    if feedback_repo is not None:
        app.state.feedback_repo = feedback_repo

    return app


def _make_run_store(run_record: dict | None):
    """准备可控测试资源与状态，供后续断言读取。"""
    store = MagicMock()
    store.get = AsyncMock(return_value=run_record)
    return store


def _make_event_store(rows: list[dict]):
    """准备可控测试资源与状态，供后续断言读取。"""
    store = MagicMock()
    store.list_messages_by_run = AsyncMock(return_value=rows)
    return store


def _make_message(seq: int) -> dict:
    """准备可控测试资源与状态，供后续断言读取。"""
    return {"seq": seq, "event_type": "on_chat_model_stream", "category": "message", "content": f"msg-{seq}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_messages_returns_envelope():
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    rows = [_make_message(i) for i in range(1, 4)]
    run_record = {"run_id": "run-1", "thread_id": "thread-1"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store(rows),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-1/messages")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "has_more" in body
    assert body["has_more"] is False
    assert len(body["data"]) == 3


def test_run_messages_404_when_run_not_found():
    """验证运行 运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    app = _make_app(
        run_store=_make_run_store(None),
        event_store=_make_event_store([]),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/missing-run/messages")
    assert response.status_code == 404
    assert "missing-run" in response.json()["detail"]


def test_run_messages_has_more_true_when_extra_row_returned():
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    # Default limit is 50; provide 51 rows
    rows = [_make_message(i) for i in range(1, 52)]  # 51 rows
    run_record = {"run_id": "run-2", "thread_id": "thread-2"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store(rows),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-2/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is True
    assert len(body["data"]) == 50  # trimmed to limit
    assert [m["seq"] for m in body["data"]] == list(range(2, 52))


def test_run_messages_default_page_keeps_newest_messages_when_extra_row_returned():
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    rows = [_make_message(i) for i in range(16, 67)]
    run_record = {"run_id": "run-2", "thread_id": "thread-2"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store(rows),
    )
    with TestClient(app) as client:
        assert_run_message_page(client, "/api/runs/run-2/messages", expected_seq=list(range(17, 67)))


def test_run_messages_before_seq_page_keeps_newest_side_when_extra_row_returned():
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    rows = [_make_message(i) for i in range(1, 18)]
    run_record = {"run_id": "run-2", "thread_id": "thread-2"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store(rows),
    )
    with TestClient(app) as client:
        assert_run_message_page(
            client,
            "/api/runs/run-2/messages?before_seq=18&limit=16",
            expected_seq=list(range(2, 18)),
        )


def test_run_messages_after_seq_page_keeps_oldest_side_when_extra_row_returned():
    """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
    rows = [_make_message(i) for i in range(11, 62)]
    run_record = {"run_id": "run-2", "thread_id": "thread-2"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store(rows),
    )
    with TestClient(app) as client:
        assert_run_message_page(
            client,
            "/api/runs/run-2/messages?after_seq=10",
            expected_seq=list(range(11, 61)),
        )


def test_run_messages_passes_after_seq_to_event_store():
    """验证运行 事件 存储在预期条件及边界场景下的可观察行为，防止相关回归。"""
    rows = [_make_message(10)]
    run_record = {"run_id": "run-3", "thread_id": "thread-3"}
    event_store = _make_event_store(rows)
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=event_store,
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-3/messages?after_seq=5")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-3",
        "run-3",
        limit=51,  # default limit(50) + 1
        before_seq=None,
        after_seq=5,
    )


def test_run_messages_respects_custom_limit():
    """验证运行 限制在预期条件及边界场景下的可观察行为，防止相关回归。"""
    rows = [_make_message(i) for i in range(1, 6)]
    run_record = {"run_id": "run-4", "thread_id": "thread-4"}
    event_store = _make_event_store(rows)
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=event_store,
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-4/messages?limit=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-4",
        "run-4",
        limit=11,  # 10 + 1
        before_seq=None,
        after_seq=None,
    )


def test_run_messages_passes_before_seq_to_event_store():
    """验证运行 事件 存储在预期条件及边界场景下的可观察行为，防止相关回归。"""
    rows = [_make_message(3)]
    run_record = {"run_id": "run-5", "thread_id": "thread-5"}
    event_store = _make_event_store(rows)
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=event_store,
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-5/messages?before_seq=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-5",
        "run-5",
        limit=51,
        before_seq=10,
        after_seq=None,
    )


def test_run_messages_empty_data():
    """验证运行 数据在预期条件及边界场景下的可观察行为，防止相关回归。"""
    run_record = {"run_id": "run-6", "thread_id": "thread-6"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store([]),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-6/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["has_more"] is False


def _make_feedback_repo(rows: list[dict]):
    """准备可控测试资源与状态，供后续断言读取。"""
    repo = MagicMock()
    repo.list_by_run = AsyncMock(return_value=rows)
    return repo


def _make_feedback(run_id: str, idx: int) -> dict:
    """准备可控测试资源与状态，供后续断言读取。"""
    return {"id": f"fb-{idx}", "run_id": run_id, "thread_id": "thread-x", "value": "up"}


# ---------------------------------------------------------------------------
# TestRunFeedback
# ---------------------------------------------------------------------------


class TestRunFeedback:
    """集中覆盖当前测试分支与回归边界。"""
    def test_returns_list_of_feedback_dicts(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        run_record = {"run_id": "run-fb-1", "thread_id": "thread-fb-1"}
        rows = [_make_feedback("run-fb-1", i) for i in range(3)]
        app = _make_app(
            run_store=_make_run_store(run_record),
            feedback_repo=_make_feedback_repo(rows),
        )
        with TestClient(app) as client:
            response = client.get("/api/runs/run-fb-1/feedback")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 3

    def test_404_when_run_not_found(self):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        app = _make_app(
            run_store=_make_run_store(None),
            feedback_repo=_make_feedback_repo([]),
        )
        with TestClient(app) as client:
            response = client.get("/api/runs/missing-run/feedback")
        assert response.status_code == 404
        assert "missing-run" in response.json()["detail"]

    def test_empty_list_when_no_feedback(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        run_record = {"run_id": "run-fb-2", "thread_id": "thread-fb-2"}
        app = _make_app(
            run_store=_make_run_store(run_record),
            feedback_repo=_make_feedback_repo([]),
        )
        with TestClient(app) as client:
            response = client.get("/api/runs/run-fb-2/feedback")
        assert response.status_code == 200
        assert response.json() == []

    def test_503_when_feedback_repo_not_configured(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        run_record = {"run_id": "run-fb-3", "thread_id": "thread-fb-3"}
        app = _make_app(
            run_store=_make_run_store(run_record),
        )
        # Explicitly set feedback_repo to None to simulate missing DB
        app.state.feedback_repo = None
        with TestClient(app) as client:
            response = client.get("/api/runs/run-fb-3/feedback")
        assert response.status_code == 503
