"""\u672c\u6a21\u5757\u8986\u76d6\u76f8\u5173\u6d4b\u8bd5\uff0c\u56fa\u5b9a\u516c\u5f00\u884c\u4e3a\u3001\u5931\u8d25\u5904\u7406\u4e0e\u72b6\u6001\u8fb9\u754c\u3002"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import channels


def _admin_user() -> User:
    """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
    return User(
        id=UUID("11111111-2222-3333-4444-555555555555"),
        email="admin@example.com",
        password_hash="x",
        system_role="admin",
    )


def _non_admin_user() -> User:
    """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
    return User(
        id=UUID("99999999-8888-7777-6666-555555555555"),
        email="user@example.com",
        password_hash="x",
        system_role="user",
    )


def test_restart_channel_requires_admin(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    service = SimpleNamespace(restart_channel=AsyncMock(return_value=True))
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_non_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/restart")

    assert response.status_code == 403
    assert "Admin privileges" in response.json()["detail"]
    service.restart_channel.assert_not_awaited()


def test_restart_channel_allows_admin(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    service = SimpleNamespace(restart_channel=AsyncMock(return_value=True))
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/restart")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Channel slack restarted successfully",
    }
    service.restart_channel.assert_awaited_once_with("slack")


def test_get_channels_status_remains_read_only(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc73\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    service = SimpleNamespace(
        get_status=lambda: {
            "service_running": True,
            "channels": {
                "slack": {
                    "enabled": True,
                    "running": True,
                }
            },
        }
    )
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_non_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.get("/api/channels/")

    assert response.status_code == 200
    assert response.json()["service_running"] is True
    assert response.json()["channels"]["slack"]["running"] is True
