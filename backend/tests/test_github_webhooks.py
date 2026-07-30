"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.channels.message_bus import MessageBus
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import github_webhooks

SECRET = "test-secret-do-not-use-in-production"
DELIVERY_ID = "12345678-1234-1234-1234-123456789abc"


def _signature(body: bytes, secret: str = SECRET) -> str:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _make_app() -> FastAPI:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    app = FastAPI()
    # 说明当前测试分支所验证的真实行为与边界。
    app.add_middleware(CSRFMiddleware)
    app.include_router(github_webhooks.router)
    return app


@pytest.fixture
def client() -> TestClient:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    return TestClient(_make_app())


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)


@pytest.fixture(autouse=True)
def _stub_channel_service(monkeypatch: pytest.MonkeyPatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()

    class _StubService:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def __init__(self) -> None:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            self.bus = bus

        def is_channel_enabled(self, name: str) -> bool:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            return True

        def get_channel_config(self, name: str) -> dict | None:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            return None

    stub = _StubService()
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: stub)
    return stub


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_ping_event_returns_200(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps({"zen": "Practicality beats purity.", "hook": {"id": 42}}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert payload["ok"] is True
    assert payload["event"] == "ping"
    assert payload["delivery"] == DELIVERY_ID
    assert payload["handled"] is True
    assert "dispatch" in payload


def test_pull_request_opened_returns_200(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {
                "number": 7,
                "title": "Add webhook receiver",
                "html_url": "https://github.com/org/repo/pull/7",
            },
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_issue_comment_returns_200(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps(
        {
            "action": "created",
            "issue": {"number": 3, "pull_request": {"url": "..."}},
            "comment": {"user": {"login": "octocat"}},
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_issues_event_returns_200(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps(
        {
            "action": "opened",
            "issue": {
                "number": 12,
                "title": "Bug: things are broken",
                "html_url": "https://github.com/org/repo/issues/12",
            },
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_pull_request_review_returns_200(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps(
        {
            "action": "submitted",
            "pull_request": {"number": 5},
            "review": {"state": "approved", "user": {"login": "reviewer"}},
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request_review",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_plain_issue_comment_is_not_pr(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps(
        {
            "action": "created",
            "issue": {"number": 7},  # 说明当前测试分支所验证的真实行为与边界。
            "comment": {"user": {"login": "octocat"}},
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    with caplog.at_level("INFO", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-GitHub-Delivery": DELIVERY_ID,
                "X-Hub-Signature-256": _signature(body),
            },
        )

    assert response.status_code == 200
    assert any("is_pr=False" in rec.message for rec in caplog.records)


def test_unknown_event_returns_200_but_unhandled(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps({"action": "started"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    body_json = response.json()
    assert body_json["ok"] is True
    assert body_json["handled"] is False
    assert body_json["event"] == "workflow_run"


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_missing_signature_returns_401(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = b'{"zen": "x"}'
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
        },
    )

    assert response.status_code == 401
    assert "X-Hub-Signature-256" in response.json()["detail"]


def test_malformed_signature_returns_401(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = b'{"zen": "x"}'
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": "not-a-valid-format",
        },
    )

    assert response.status_code == 401


def test_signature_mismatch_returns_401(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = b'{"zen": "x"}'
    # 说明当前测试分支所验证的真实行为与边界。
    bad_sig = _signature(body, secret="wrong-secret")
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": bad_sig,
        },
    )

    assert response.status_code == 401


def test_signature_verified_against_exact_bytes(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = b'{"zen":"x","other":1}'  # 说明当前测试分支所验证的真实行为与边界。
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_unset_secret_rejects_with_503_by_default(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    body = json.dumps({"zen": "ok"}).encode()

    with caplog.at_level("ERROR", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
        )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "GITHUB_WEBHOOK_SECRET" in detail
    assert "DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS" in detail
    assert any("rejecting delivery" in rec.message for rec in caplog.records)


def test_unset_secret_with_dev_optin_accepts_unverified(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", "1")
    body = json.dumps({"zen": "ok"}).encode()

    with caplog.at_level("WARNING", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
        )

    assert response.status_code == 200
    assert any("UNVERIFIED delivery" in rec.message and "dev/loopback mode ONLY" in rec.message for rec in caplog.records)


def test_empty_string_secret_rejects_without_optin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "   ")
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
    )

    assert response.status_code == 503


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "   ", "anything-else"])
def test_unverified_optin_falsy_values_reject(client: TestClient, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", value)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
    )

    assert response.status_code == 503


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "ON"])
def test_unverified_optin_truthy_values_accept(client: TestClient, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", value)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
    )

    assert response.status_code == 200


def test_is_route_enabled_requires_secret_or_optin(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    assert github_webhooks.is_route_enabled() is False

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "anything")
    assert github_webhooks.is_route_enabled() is True

    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", "1")
    assert github_webhooks.is_route_enabled() is True

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "  ")
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    assert github_webhooks.is_route_enabled() is False


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_missing_event_header_returns_400(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = b'{"zen": "x"}'
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 400
    assert "X-GitHub-Event" in response.json()["detail"]


def test_invalid_json_body_returns_400(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = b"this-is-not-json"
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_csrf_middleware_does_not_block_webhook(client: TestClient) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_dispatch_result_included_in_response(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""

    fake = AsyncMock(return_value={"matched_agents": ["x"], "fired_agents": ["x"], "skipped": []})
    monkeypatch.setattr(github_webhooks, "fanout_event", fake)

    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["dispatch"] == {"matched_agents": ["x"], "fired_agents": ["x"], "skipped": []}
    assert fake.await_count == 1


def test_dispatch_failure_returns_503_so_github_retries(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""

    async def fake_fanout(*args, **kwargs) -> dict:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        raise RuntimeError("transient registry hiccup")

    monkeypatch.setattr(github_webhooks, "fanout_event", fake_fanout)

    body = json.dumps({"zen": "ok"}).encode()
    with caplog.at_level("ERROR", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": DELIVERY_ID,
                "X-Hub-Signature-256": _signature(body),
            },
        )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "fan-out failed" in detail
    assert DELIVERY_ID in detail
    assert "transient registry hiccup" in detail
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert any("fanout failed" in rec.message for rec in caplog.records)


def test_dispatch_failure_503_lets_github_redeliver_successfully(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    calls: list[int] = []

    async def flaky_fanout(*args, **kwargs) -> dict:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"matched_agents": [], "fired_agents": [], "skipped": []}

    monkeypatch.setattr(github_webhooks, "fanout_event", flaky_fanout)

    body = json.dumps({"zen": "ok"}).encode()
    first = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert first.status_code == 503

    # 说明当前测试分支所验证的真实行为与边界。
    second = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert second.status_code == 200
    assert second.json()["dispatch"] == {"matched_agents": [], "fired_agents": [], "skipped": []}


def test_unknown_event_skips_dispatcher(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fake = AsyncMock(return_value={})
    monkeypatch.setattr(github_webhooks, "fanout_event", fake)

    body = json.dumps({"action": "x"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert response.json()["dispatch"] is None
    assert fake.await_count == 0


def test_missing_channel_service_does_not_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: None)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["dispatch"]["error"] == "channel_service_not_available"


def test_channel_disabled_skips_fanout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()

    class _DisabledService:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def __init__(self) -> None:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            self.bus = bus

        def is_channel_enabled(self, name: str) -> bool:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            return False  # 说明当前测试分支所验证的真实行为与边界。

        def get_channel_config(self, name: str) -> dict | None:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            return None

    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: _DisabledService())

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    fake_fanout = AsyncMock(return_value={"matched": ["should-not-run"]})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["handled"] is True
    assert payload["dispatch"] == {"skipped": "channel_disabled"}
    assert fake_fanout.await_count == 0


def test_channel_enabled_dispatches_normally(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fake_fanout = AsyncMock(return_value={"matched": ["agent-a"]})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["dispatch"] == {"matched": ["agent-a"]}
    assert fake_fanout.await_count == 1


def test_operator_default_mention_login_is_threaded_to_fanout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    bus = MessageBus()

    class _ConfiguredService:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        def __init__(self) -> None:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            self.bus = bus

        def is_channel_enabled(self, name: str) -> bool:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            return True

        def get_channel_config(self, name: str) -> dict | None:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            if name == "github":
                return {"enabled": True, "default_mention_login": "deerflow-bot"}
            return None

    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: _ConfiguredService())

    fake_fanout = AsyncMock(return_value={"matched_agents": [], "fired_agents": [], "skipped": []})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert fake_fanout.await_count == 1
    # 说明当前测试分支所验证的真实行为与边界。
    _, kwargs = fake_fanout.await_args
    assert kwargs["operator_default_mention_login"] == "deerflow-bot"


def test_operator_default_mention_login_absent_passes_none(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fake_fanout = AsyncMock(return_value={"matched_agents": [], "fired_agents": [], "skipped": []})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    _, kwargs = fake_fanout.await_args
    assert kwargs["operator_default_mention_login"] is None


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_verify_signature_helper_constant_time_equal() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    body = b'{"x": 1}'
    sig = _signature(body)
    assert github_webhooks._verify_signature(SECRET, body, sig) is True


def test_verify_signature_rejects_none() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert github_webhooks._verify_signature(SECRET, b"x", None) is False


def test_verify_signature_rejects_missing_prefix() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert github_webhooks._verify_signature(SECRET, b"x", "abcdef0123") is False


def test_summarise_event_handles_missing_fields() -> None:
    # 说明当前测试分支所验证的真实行为与边界。
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    result = github_webhooks._summarise_event("pull_request", {})
    assert "pull_request" in result


def test_summarise_event_unknown_event_falls_back() -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    result = github_webhooks._summarise_event("deployment_status", {"action": "success", "repository": {"full_name": "a/b"}})
    assert "deployment_status" in result
    assert "success" in result
