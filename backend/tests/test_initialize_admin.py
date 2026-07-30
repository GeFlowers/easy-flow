"""覆盖初始化管理员接口的首启创建、重复拦截、密码校验与匿名访问边界。"""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-initialize-admin-min-32")

from app.gateway.auth.config import AuthConfig, set_auth_config

_TEST_SECRET = "test-secret-key-initialize-admin-min-32"


@pytest.fixture(autouse=True)
def _setup_auth(tmp_path):
    """为每个用例创建独立的轻量数据库引擎、认证配置与干净状态缓存。"""
    from app.gateway import deps
    from app.gateway.routers.auth import _SETUP_STATUS_CACHE, _SETUP_STATUS_INFLIGHT
    from deerflow.persistence.engine import close_engine, init_engine

    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    url = f"sqlite+aiosqlite:///{tmp_path}/init_admin.db"
    asyncio.run(init_engine("sqlite", url=url, sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    _SETUP_STATUS_CACHE.clear()
    _SETUP_STATUS_INFLIGHT.clear()
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        _SETUP_STATUS_CACHE.clear()
        _SETUP_STATUS_INFLIGHT.clear()
        asyncio.run(close_engine())


@pytest.fixture()
def client(_setup_auth):
    """提供不触发生命周期配置加载、但已完成认证依赖初始化的测试客户端。"""
    from app.gateway.app import create_app
    from app.gateway.auth.config import AuthConfig, set_auth_config

    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    app = create_app()
    # 不以上下文管理器方式创建客户端：那会启动依赖配置文件的完整生命周期。
    # 认证端点无需该生命周期，因为前置夹具已经准备好了持久化引擎。
    yield TestClient(app)


def _init_payload(**extra):
    """构造可通过初始化接口校验的默认管理员请求，并允许调用方覆盖字段。"""
    return {
        "email": "admin@example.com",
        "password": "Str0ng!Pass99",
        **extra,
    }


# ── 成功初始化路径 ────────────────────────────────────────────────────────


def test_initialize_creates_admin_and_sets_cookie(client):
    """验证无管理员时初始化返回 201、管理员角色与会话凭据。"""
    resp = client.post("/api/v1/auth/initialize", json=_init_payload())
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "admin@example.com"
    assert data["system_role"] == "admin"
    assert "access_token" in resp.cookies


def test_initialize_needs_setup_false(client):
    """验证初始化创建的管理员在个人信息接口中已不需要完成设置。"""
    client.post("/api/v1/auth/initialize", json=_init_payload())
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["needs_setup"] is False


# ── 已初始化后的拒绝路径 ──────────────────────────────────────────────────


def test_initialize_rejected_when_admin_exists(client):
    """验证已有管理员后再次初始化返回系统已初始化的 409 错误。"""
    client.post("/api/v1/auth/initialize", json=_init_payload())
    resp2 = client.post(
        "/api/v1/auth/initialize",
        json={**_init_payload(), "email": "other@example.com"},
    )
    assert resp2.status_code == 409
    body = resp2.json()
    assert body["detail"]["code"] == "system_already_initialized"


def test_initialize_register_does_not_block_initialization(client):
    """验证普通用户存在时仍可初始化首个管理员，因为只统计管理员数量。"""
    # 先注册普通用户，验证其不会影响管理员初始化资格。
    client.post("/api/v1/auth/register", json={"email": "regular@example.com", "password": "Tr0ub4dor3a"})
    # 初始化只检查管理员数量，不检查所有用户总数，因此仍应成功。
    resp = client.post("/api/v1/auth/initialize", json=_init_payload())
    assert resp.status_code == 201
    assert resp.json()["system_role"] == "admin"


def test_initialize_existing_regular_user_email_reports_email_conflict(client):
    """验证无管理员时复用普通用户邮箱返回邮箱冲突，而非已初始化错误。"""
    client.post("/api/v1/auth/register", json={"email": "regular@example.com", "password": "Tr0ub4dor3a"})

    resp = client.post(
        "/api/v1/auth/initialize",
        json={**_init_payload(), "email": "regular@example.com"},
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["code"] == "email_already_exists"
    assert client.get("/api/v1/auth/setup-status").json()["needs_setup"] is True


# ── 初始化端点的匿名访问边界 ──────────────────────────────────────────────


def test_initialize_accessible_without_cookie(client):
    """验证请求不携带访问令牌凭据也能完成首次初始化。"""
    resp = client.post(
        "/api/v1/auth/initialize",
        json=_init_payload(),
        cookies={},
    )
    assert resp.status_code == 201


# ── 密码强度校验 ──────────────────────────────────────────────────────────


def test_initialize_rejects_short_password(client):
    """验证短于最小长度的管理员密码被接口以 422 拒绝。"""
    resp = client.post(
        "/api/v1/auth/initialize",
        json={**_init_payload(), "password": "short"},
    )
    assert resp.status_code == 422


def test_initialize_rejects_common_password(client):
    """验证常见弱密码即使长度足够也被接口以 422 拒绝。"""
    resp = client.post(
        "/api/v1/auth/initialize",
        json={**_init_payload(), "password": "password123"},
    )
    assert resp.status_code == 422


# ── 设置状态与初始化结果一致 ──────────────────────────────────────────────


def test_setup_status_before_initialization(client):
    """验证尚未初始化时设置状态接口明确要求完成设置。"""
    resp = client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needs_setup"] is True


def test_setup_status_after_initialization(client):
    """验证初始化成功后设置状态接口立即报告无需设置。"""
    client.post("/api/v1/auth/initialize", json=_init_payload())
    resp = client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needs_setup"] is False


def test_setup_status_true_when_only_regular_user_exists(client):
    """验证只有普通用户时设置状态仍要求初始化管理员。"""
    client.post("/api/v1/auth/register", json={"email": "regular@example.com", "password": "Tr0ub4dor3a"})
    resp = client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needs_setup"] is True


def test_setup_status_returns_cached_result_on_rapid_calls(client):
    """验证短时间内重复查询复用缓存并返回相同的成功状态。"""
    client.post("/api/v1/auth/initialize", json=_init_payload())

    # 首次调用计算并缓存当前设置状态。
    resp1 = client.get("/api/v1/auth/setup-status")
    assert resp1.status_code == 200

    # 紧随其后的调用应命中缓存，而不是触发限流。
    resp2 = client.get("/api/v1/auth/setup-status")
    assert resp2.status_code == 200
    assert resp2.json() == resp1.json()
    assert resp2.json()["needs_setup"] is False


def test_setup_status_does_not_return_stale_true_after_initialize(client):
    """验证初始化会失效旧的需设置缓存，不会继续返回过期真值。"""
    before = client.get("/api/v1/auth/setup-status")
    assert before.status_code == 200
    assert before.json()["needs_setup"] is True

    init = client.post("/api/v1/auth/initialize", json=_init_payload())
    assert init.status_code == 201

    after = client.get("/api/v1/auth/setup-status")
    assert after.status_code == 200
    assert after.json()["needs_setup"] is False


@pytest.mark.asyncio
async def test_setup_status_single_flight_per_ip(monkeypatch):
    """验证同一来源地址的并发状态查询共用一次进行中的管理员计数。"""
    from starlette.requests import Request

    from app.gateway.routers.auth import (
        _SETUP_STATUS_CACHE,
        _SETUP_STATUS_INFLIGHT,
        setup_status,
    )

    class _Provider:
        """模拟可计数管理员并暴露调用次数的认证数据提供者。"""

        def __init__(self):
            """初始化管理员计数调用次数。"""
            self.calls = 0

        async def count_admin_users(self):
            """延迟返回零管理员，以便并发请求重叠并验证单飞控制。"""
            self.calls += 1
            await asyncio.sleep(0.05)
            return 0

    provider = _Provider()
    monkeypatch.setattr("app.gateway.routers.auth.get_local_provider", lambda: provider)
    _SETUP_STATUS_CACHE.clear()
    _SETUP_STATUS_INFLIGHT.clear()

    def _request() -> Request:
        """构造来自同一回环地址的设置状态请求。"""
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/auth/setup-status",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            }
        )

    results = await asyncio.gather(
        setup_status(_request()),
        setup_status(_request()),
        setup_status(_request()),
    )

    assert all(result["needs_setup"] is True for result in results)
    assert provider.calls == 1
