"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

import pytest
from starlette.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware, _is_public
from app.gateway.csrf_middleware import CSRFMiddleware

# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/health/",
        "/docs",
        "/docs/",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/login/local",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
    ],
)
def test_public_paths(path: str):
    """验证“公开该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert _is_public(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/models",
        "/api/mcp/config",
        "/api/mcp/cache/reset",
        "/api/memory",
        "/api/skills",
        "/api/threads/123",
        "/api/threads/123/uploads",
        "/api/agents",
        "/api/channels",
        "/api/channels/providers",
        "/api/channels/slack/connect",
        "/api/runs/stream",
        "/api/threads/123/runs",
        "/api/v1/auth/me",
        "/api/v1/auth/change-password",
    ],
)
def test_protected_paths(path: str):
    """验证“受保护该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert _is_public(path) is False


# ── 尾部斜杠/归一化边缘情况──────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login/local/",
        "/api/v1/auth/register/",
        "/api/v1/auth/logout/",
        "/api/v1/auth/setup-status/",
    ],
)
def test_public_auth_paths_with_trailing_slash(path: str):
    """验证“公开认证该项使用该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert _is_public(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/models/",
        "/api/v1/auth/me/",
        "/api/v1/auth/change-password/",
    ],
)
def test_protected_paths_with_trailing_slash(path: str):
    """验证“受保护该项使用该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert _is_public(path) is False


def test_unknown_api_path_is_protected():
    """验证“该项接口路径该项受保护”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert _is_public("/api/new-feature") is False
    assert _is_public("/api/v2/something") is False
    assert _is_public("/api/v1/auth/new-endpoint") is False


# ── 中间件集成测试 ──────────────────────────────────────────


def _make_app():
    """为“构造应用”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    from fastapi import FastAPI, Request

    from deerflow.runtime.user_context import get_effective_user_id

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/health")
    async def health():
        """为“健康检查”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    async def auth_me(request: Request):
        """为“认证该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        from app.gateway.deps import get_current_user_from_request

        user = await get_current_user_from_request(request)
        return {
            "id": str(user.id),
            "email": user.email,
            "system_role": user.system_role,
            "needs_setup": user.needs_setup,
        }

    @app.get("/api/v1/auth/setup-status")
    async def setup_status():
        """为“设置该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"needs_setup": False}

    @app.get("/api/models")
    async def models_get():
        """为“该项获取”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"models": []}

    @app.get("/api/whoami")
    async def whoami(request: Request):
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        user = request.state.user
        return {
            "id": str(user.id),
            "email": getattr(user, "email", None),
            "system_role": getattr(user, "system_role", None),
            "context_user_id": get_effective_user_id(),
        }

    @app.get("/api/current-user-from-dep")
    async def current_user_from_dep(request: Request):
        """为“当前用户该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        from app.gateway.deps import get_current_user_from_request

        user = await get_current_user_from_request(request)
        state_user = request.state.user
        return {
            "id": str(user.id),
            "state_id": str(state_user.id),
            "auth_source": request.state.auth_source,
            "context_user_id": get_effective_user_id(),
        }

    @app.put("/api/mcp/config")
    async def mcp_put():
        """为“该项更新”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    @app.post("/api/mcp/cache/reset")
    async def mcp_cache_reset():
        """为“该项该项重置”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    @app.delete("/api/threads/abc")
    async def thread_delete():
        """为“线程删除”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    @app.patch("/api/threads/abc")
    async def thread_patch():
        """为“线程局部更新”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    @app.post("/api/threads/abc/runs/stream")
    async def stream():
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    @app.get("/api/future-endpoint")
    async def future():
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    return app


def _make_auth_csrf_app():
    """为“构造认证跨站请求伪造防护应用”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/threads/abc/runs/stream")
    async def protected_mutation():
        """为“受保护该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    return app


@pytest.fixture
def client(monkeypatch):
    """执行“客户端”的测试辅助步骤，维持断言所依赖的状态、失败分支与资源生命周期。"""
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    return TestClient(_make_app())


def test_public_path_no_cookie(client):
    """验证“公开路径该项令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.get("/health")
    assert res.status_code == 200


def test_public_auth_path_no_cookie(client):
    """验证“公开认证路径该项令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.get("/api/v1/auth/setup-status")
    assert res.status_code == 200


def test_protected_auth_path_no_cookie(client):
    """验证“受保护认证路径该项令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_protected_path_no_cookie_returns_401(client):
    """验证“受保护路径该项令牌存储返回该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.get("/api/models")
    assert res.status_code == 401
    body = res.json()
    assert body["detail"]["code"] == "not_authenticated"


def test_auth_disabled_allows_protected_path_without_cookie(monkeypatch):
    """验证“认证该项允许受保护路径不使用令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/models")

    assert res.status_code == 200
    assert res.json() == {"models": []}


def test_auth_disabled_stamps_default_admin_user_without_cookie(monkeypatch):
    """验证“认证该项该项默认值管理员用户不使用令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/whoami")

    assert res.status_code == 200
    assert res.json() == {
        "id": "default",
        "email": "default@test.local",
        "system_role": "admin",
        "context_user_id": "default",
    }


def test_auth_disabled_auth_me_reuses_middleware_user_without_cookie(monkeypatch):
    """验证“认证该项认证该项该项中间件用户不使用令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/v1/auth/me")

    assert res.status_code == 200
    assert res.json() == {
        "id": "default",
        "email": "default@test.local",
        "system_role": "admin",
        "needs_setup": False,
    }


def test_auth_disabled_does_not_clobber_valid_session_cookie(monkeypatch):
    """验证“认证该项该项该项该项有效会话令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from types import SimpleNamespace

    async def fake_current_user(request):
        """为“该项当前用户”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return SimpleNamespace(
            id="session-user",
            email="session@test.local",
            system_role="user",
            needs_setup=False,
        )

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", fake_current_user)
    client = TestClient(_make_app())

    res = client.get("/api/whoami", cookies={"access_token": "valid-session"})

    assert res.status_code == 200
    assert res.json() == {
        "id": "session-user",
        "email": "session@test.local",
        "system_role": "user",
        "context_user_id": "session-user",
    }


def test_auth_disabled_does_not_clobber_internal_auth_identity(monkeypatch):
    """验证“认证该项该项该项该项内部认证身份”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.internal_auth import create_internal_auth_headers
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get(
        "/api/current-user-from-dep",
        headers=create_internal_auth_headers(),
    )

    assert res.status_code == 200
    assert res.json() == {
        "id": DEFAULT_USER_ID,
        "state_id": DEFAULT_USER_ID,
        "auth_source": "internal",
        "context_user_id": DEFAULT_USER_ID,
    }


def test_auth_disabled_skips_csrf_for_state_changing_requests(monkeypatch):
    """验证“认证该项该项跨站请求伪造防护该项状态该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_auth_csrf_app())

    res = client.post("/api/threads/abc/runs/stream")

    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_auth_disabled_is_ignored_in_explicit_production_env(monkeypatch):
    """验证“认证该项该项该项该项显式生产环境环境变量”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("DEER_FLOW_ENV", "production")
    client = TestClient(_make_app())

    res = client.get("/api/models")

    assert res.status_code == 401


def test_auth_disabled_startup_warning_when_effective(monkeypatch, caplog):
    """验证“认证该项启动警告当有效”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth_disabled import warn_if_auth_disabled_enabled

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    with caplog.at_level("WARNING", logger="app.gateway.auth_disabled"):
        warn_if_auth_disabled_enabled()

    assert "authentication is bypassed" in caplog.text
    assert "default" in caplog.text


def test_auth_disabled_startup_warning_suppressed_in_explicit_production_env(monkeypatch, caplog):
    """验证“认证该项启动警告该项该项显式生产环境环境变量”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth_disabled import warn_if_auth_disabled_enabled

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with caplog.at_level("WARNING", logger="app.gateway.auth_disabled"):
        warn_if_auth_disabled_enabled()

    assert "authentication is bypassed" not in caplog.text


def test_protected_path_with_junk_cookie_rejected(client):
    """验证“受保护路径使用该项令牌存储该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client.cookies.set("access_token", "some-token")
    res = client.get("/api/models")
    assert res.status_code == 401


def test_protected_post_no_cookie_returns_401(client):
    """验证“受保护提交该项令牌存储返回该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.post("/api/threads/abc/runs/stream")
    assert res.status_code == 401


def test_mcp_cache_reset_post_no_cookie_returns_401(client):
    """验证“该项该项重置提交该项令牌存储返回该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.post("/api/mcp/cache/reset")
    assert res.status_code == 401


def test_protected_post_with_internal_auth_header_passes():
    """验证“受保护提交使用内部认证标头该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.internal_auth import create_internal_auth_headers

    app = _make_app()
    client = TestClient(app)

    res = client.post(
        "/api/threads/abc/runs/stream",
        headers=create_internal_auth_headers(),
    )

    assert res.status_code == 200


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_protected_put_no_cookie(client):
    """验证“受保护更新该项令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.put("/api/mcp/config")
    assert res.status_code == 401


def test_protected_delete_no_cookie(client):
    """验证“受保护删除该项令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.delete("/api/threads/abc")
    assert res.status_code == 401


def test_protected_patch_no_cookie(client):
    """验证“受保护局部更新该项令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.patch("/api/threads/abc")
    assert res.status_code == 401


def test_put_with_junk_cookie_rejected(client):
    """验证“更新使用该项令牌存储该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client.cookies.set("access_token", "tok")
    res = client.put("/api/mcp/config")
    assert res.status_code == 401


def test_delete_with_junk_cookie_rejected(client):
    """验证“删除使用该项令牌存储该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client.cookies.set("access_token", "tok")
    res = client.delete("/api/threads/abc")
    assert res.status_code == 401


# ── 失败关闭：未来终点未知──────────────────────────────────


def test_unknown_endpoint_no_cookie_returns_401(client):
    """验证“该项端点该项令牌存储返回该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    res = client.get("/api/future-endpoint")
    assert res.status_code == 401


def test_unknown_endpoint_with_junk_cookie_rejected(client):
    """验证“该项端点使用该项令牌存储该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client.cookies.set("access_token", "tok")
    res = client.get("/api/future-endpoint")
    assert res.status_code == 401
