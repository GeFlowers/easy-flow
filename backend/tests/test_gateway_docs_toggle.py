"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _reset_gateway_config():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import app.gateway.config as cfg

    cfg._gateway_config = None


@pytest.fixture(autouse=True)
def _clean_config():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    _reset_gateway_config()
    yield
    _reset_gateway_config()


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_enable_docs_defaults_to_true():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with patch.dict(os.environ, {}, clear=False):
        if "GATEWAY_ENABLE_DOCS" in os.environ:
            del os.environ["GATEWAY_ENABLE_DOCS"]
        _reset_gateway_config()
        from app.gateway.config import get_gateway_config

        config = get_gateway_config()
        assert config.enable_docs is True


def test_enable_docs_false():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": "false"}):
        _reset_gateway_config()
        from app.gateway.config import get_gateway_config

        config = get_gateway_config()
        assert config.enable_docs is False


def test_enable_docs_case_insensitive():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    for value in ("FALSE", "False", "false"):
        with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": value}):
            _reset_gateway_config()
            from app.gateway.config import get_gateway_config

            config = get_gateway_config()
            assert config.enable_docs is False, f"Expected False for GATEWAY_ENABLE_DOCS={value}"


def test_enable_docs_unexpected_value_disables():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    for value in ("0", "no", "off", "anything"):
        with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": value}):
            _reset_gateway_config()
            from app.gateway.config import get_gateway_config

            config = get_gateway_config()
            assert config.enable_docs is False, f"Expected False for GATEWAY_ENABLE_DOCS={value}"


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def test_docs_endpoints_available_by_default():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with patch.dict(os.environ, {}, clear=False):
        if "GATEWAY_ENABLE_DOCS" in os.environ:
            del os.environ["GATEWAY_ENABLE_DOCS"]
        _reset_gateway_config()
        from app.gateway.app import create_app

        app = create_app()
        client = TestClient(app)
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_docs_endpoints_disabled_when_false():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": "false"}):
        _reset_gateway_config()
        from app.gateway.app import create_app

        app = create_app()
        client = TestClient(app)
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_health_still_works_when_docs_disabled():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": "false"}):
        _reset_gateway_config()
        from app.gateway.app import create_app

        app = create_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# 说明当前测试分支所验证的真实行为与边界。
# ---------------------------------------------------------------------------


def _make_gateway_client(cors_origins: str) -> TestClient:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    with patch.dict(os.environ, {"GATEWAY_CORS_ORIGINS": cors_origins}):
        _reset_gateway_config()
        from app.gateway.app import create_app

        return TestClient(create_app())


def test_gateway_cors_allows_configured_origin():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    client = _make_gateway_client("https://app.example")

    response = client.get("/health", headers={"Origin": "https://app.example"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_gateway_cors_rejects_unconfigured_origin():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    client = _make_gateway_client("https://app.example")

    response = client.get("/health", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_gateway_cors_normalizes_configured_default_port():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    client = _make_gateway_client("https://app.example:443")

    response = client.get("/health", headers={"Origin": "https://app.example"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
