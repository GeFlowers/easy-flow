"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

import os
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError
from app.gateway.auth.jwt import decode_token
from app.gateway.csrf_middleware import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    is_auth_endpoint,
    should_check_csrf,
)

# ── 设置 ──────────────────────────────────────────────────────────

_TEST_SECRET = "test-secret-for-auth-type-system-tests-min32"


@pytest.fixture(autouse=True)
def _persistence_engine(tmp_path):
    """为“持久化该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    import asyncio

    from app.gateway import deps
    from deerflow.persistence.engine import close_engine, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path}/auth_types.db"
    asyncio.run(init_engine("sqlite", url=url, sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        asyncio.run(close_engine())


def _setup_config():
    """为“设置配置”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


class _FakeRequest:
    """归集“该项请求”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def __init__(self, path: str, method: str = "POST"):
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self.method = method

        class _URL:
            """归集“网址”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            def __init__(self, p):
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                self.path = p

        self.url = _URL(path)
        self.cookies = {}
        self.headers = {}


def test_csrf_exempts_login_local():
    """验证“跨站请求伪造防护该项登录本地”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/auth/login/local")
    assert is_auth_endpoint(req) is True


def test_csrf_exempts_login_local_trailing_slash():
    """验证“跨站请求伪造防护该项登录本地该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/auth/login/local/")
    assert is_auth_endpoint(req) is True


def test_csrf_exempts_logout():
    """验证“跨站请求伪造防护该项登出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/auth/logout")
    assert is_auth_endpoint(req) is True


def test_csrf_exempts_register():
    """验证“跨站请求伪造防护该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/auth/register")
    assert is_auth_endpoint(req) is True


def test_csrf_does_not_exempt_old_login_path():
    """验证“跨站请求伪造防护该项该项该项旧的登录路径”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/auth/login")
    assert is_auth_endpoint(req) is False


def test_csrf_does_not_exempt_me():
    """验证“跨站请求伪造防护该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/auth/me")
    assert is_auth_endpoint(req) is False


def test_csrf_skips_get_requests():
    """验证“跨站请求伪造防护该项获取该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/auth/me", method="GET")
    assert should_check_csrf(req) is False


def test_csrf_checks_post_to_protected():
    """验证“跨站请求伪造防护该项提交该项受保护”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    req = _FakeRequest("/api/v1/some/endpoint", method="POST")
    assert should_check_csrf(req) is True


# ── 结构化错误响应格式 ────────────────────────────────


def test_auth_error_response_has_code_and_message():
    """验证“认证错误响应该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    err = AuthErrorResponse(
        code=AuthErrorCode.INVALID_CREDENTIALS,
        message="Wrong password",
    )
    d = err.model_dump()
    assert "code" in d
    assert "message" in d
    assert d["code"] == "invalid_credentials"


def test_auth_error_response_all_codes_serializable():
    """验证“认证错误响应全部该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    for code in AuthErrorCode:
        err = AuthErrorResponse(code=code, message=f"Test {code.value}")
        d = err.model_dump()
        assert d["code"] == code.value


# ── 解码令牌调用者模式 ────────────────────────────────────────


def test_decode_token_expired_maps_to_token_expired_code():
    """验证“解码令牌过期该项该项令牌过期该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    expired = {"sub": "u1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired, _TEST_SECRET, algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.EXPIRED

    # 验证路由处理程序中使用的映射模式
    code = AuthErrorCode.TOKEN_EXPIRED if result == TokenError.EXPIRED else AuthErrorCode.TOKEN_INVALID
    assert code == AuthErrorCode.TOKEN_EXPIRED


def test_decode_token_invalid_sig_maps_to_token_invalid_code():
    """验证“解码令牌非法该项该项该项令牌非法该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    payload = {"sub": "u1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-key", algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.INVALID_SIGNATURE

    code = AuthErrorCode.TOKEN_EXPIRED if result == TokenError.EXPIRED else AuthErrorCode.TOKEN_INVALID
    assert code == AuthErrorCode.TOKEN_INVALID


def test_decode_token_malformed_maps_to_token_invalid_code():
    """验证“解码令牌格式错误该项该项令牌非法该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    result = decode_token("garbage")
    assert result == TokenError.MALFORMED

    code = AuthErrorCode.TOKEN_EXPIRED if result == TokenError.EXPIRED else AuthErrorCode.TOKEN_INVALID
    assert code == AuthErrorCode.TOKEN_INVALID


# ── 登录响应格式 ──────────────────────────────────────────────


def test_login_response_model_has_no_access_token():
    """验证“登录响应该项该项该项该项令牌”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import LoginResponse

    resp = LoginResponse(expires_in=604800)
    d = resp.model_dump()
    assert "access_token" not in d
    assert "expires_in" in d
    assert d["expires_in"] == 604800


def test_login_response_model_fields():
    """验证“登录响应该项字段”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import LoginResponse

    fields = set(LoginResponse.model_fields.keys())
    assert fields == {"expires_in", "needs_setup"}


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_auth_config_token_expiry_used_in_login_response():
    """验证“认证配置令牌有效期该项该项登录响应”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import LoginResponse

    expected_seconds = 14 * 24 * 3600
    resp = LoginResponse(expires_in=expected_seconds)
    assert resp.expires_in == expected_seconds


# ── 用户响应类型保留────────────────────────────────────


def test_user_response_system_role_literal():
    """验证“用户响应系统该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth.models import UserResponse

    # 有效角色
    resp = UserResponse(id="1", email="a@b.com", system_role="admin")
    assert resp.system_role == "admin"

    resp = UserResponse(id="1", email="a@b.com", system_role="user")
    assert resp.system_role == "user"


def test_user_response_rejects_invalid_role():
    """验证“用户响应拒绝非法该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth.models import UserResponse

    with pytest.raises(ValidationError):
        UserResponse(id="1", email="a@b.com", system_role="superadmin")


# ══════════════════════════════════════════════════════════════════════
# 不愉快的路径/边缘情况
# ══════════════════════════════════════════════════════════════════════


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_get_current_user_no_cookie_returns_not_authenticated():
    """验证“获取当前用户该项令牌存储返回该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    mock_request = type("MockRequest", (), {"cookies": {}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "not_authenticated"


def test_get_current_user_expired_token_returns_token_expired():
    """验证“获取当前用户过期令牌返回令牌过期”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    _setup_config()
    expired = {"sub": "u1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired, _TEST_SECRET, algorithm="HS256")

    mock_request = type("MockRequest", (), {"cookies": {"access_token": token}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "token_expired"


def test_get_current_user_invalid_token_returns_token_invalid():
    """验证“获取当前用户非法令牌返回令牌非法”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    _setup_config()
    payload = {"sub": "u1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")

    mock_request = type("MockRequest", (), {"cookies": {"access_token": token}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "token_invalid"


def test_get_current_user_malformed_token_returns_token_invalid():
    """验证“获取当前用户格式错误令牌返回令牌非法”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    _setup_config()
    mock_request = type("MockRequest", (), {"cookies": {"access_token": "not-a-jwt"}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "token_invalid"


# ── 解码令牌边缘情况 ──────────────────────────────────────────


def test_decode_token_empty_string_returns_malformed():
    """验证“解码令牌空值字符串返回格式错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    result = decode_token("")
    assert result == TokenError.MALFORMED


def test_decode_token_whitespace_returns_malformed():
    """验证“解码令牌该项返回格式错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    result = decode_token("   ")
    assert result == TokenError.MALFORMED


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_auth_config_missing_jwt_secret_raises():
    """验证“认证配置缺失令牌密钥抛出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    with pytest.raises(ValidationError):
        AuthConfig()


def test_auth_config_token_expiry_zero_raises():
    """验证“认证配置令牌有效期该项抛出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    with pytest.raises(ValidationError):
        AuthConfig(jwt_secret="secret", token_expiry_days=0)


def test_auth_config_token_expiry_31_raises():
    """验证“认证配置令牌有效期该项抛出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    with pytest.raises(ValidationError):
        AuthConfig(jwt_secret="secret", token_expiry_days=31)


def test_auth_config_token_expiry_boundary_1_ok():
    """验证“认证配置令牌有效期该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config = AuthConfig(jwt_secret="secret", token_expiry_days=1)
    assert config.token_expiry_days == 1


def test_auth_config_token_expiry_boundary_30_ok():
    """验证“认证配置令牌有效期该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    config = AuthConfig(jwt_secret="secret", token_expiry_days=30)
    assert config.token_expiry_days == 30


def test_get_auth_config_missing_env_var_generates_ephemeral(caplog):
    """验证“获取认证配置缺失环境变量该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import logging

    import app.gateway.auth.config as cfg

    old = cfg._auth_config
    cfg._auth_config = None
    try:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AUTH_JWT_SECRET", None)
            with caplog.at_level(logging.WARNING):
                config = cfg.get_auth_config()
            assert config.jwt_secret
            assert any("AUTH_JWT_SECRET" in msg for msg in caplog.messages)
    finally:
        cfg._auth_config = old


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def _make_csrf_app():
    """为“构造跨站请求伪造防护应用”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    from fastapi import HTTPException as _HTTPException
    from fastapi.responses import JSONResponse as _JSONResponse

    app = FastAPI()

    @app.exception_handler(_HTTPException)
    async def _http_exc_handler(request, exc):
        """为“超文本传输协议该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return _JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.add_middleware(CSRFMiddleware)

    @app.post("/api/v1/test/protected")
    async def protected():
        """为“受保护”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    @app.post("/api/v1/auth/login/local")
    async def login():
        """为“登录”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    @app.get("/api/v1/test/read")
    async def read_endpoint():
        """为“读取端点”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    return app


def test_csrf_middleware_blocks_post_without_token():
    """验证“跨站请求伪造防护中间件该项提交不使用令牌”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client = TestClient(_make_csrf_app())
    resp = client.post("/api/v1/test/protected")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]
    assert "missing" in resp.json()["detail"].lower()


def test_csrf_middleware_blocks_post_with_mismatched_token():
    """验证“跨站请求伪造防护中间件该项提交使用该项令牌”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client = TestClient(_make_csrf_app())
    client.cookies.set(CSRF_COOKIE_NAME, "token-a")
    resp = client.post(
        "/api/v1/test/protected",
        headers={CSRF_HEADER_NAME: "token-b"},
    )
    assert resp.status_code == 403
    assert "mismatch" in resp.json()["detail"].lower()


def test_csrf_middleware_allows_post_with_matching_token():
    """验证“跨站请求伪造防护中间件允许提交使用该项令牌”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client = TestClient(_make_csrf_app())
    token = secrets.token_urlsafe(64)
    client.cookies.set(CSRF_COOKIE_NAME, token)
    resp = client.post(
        "/api/v1/test/protected",
        headers={CSRF_HEADER_NAME: token},
    )
    assert resp.status_code == 200


def test_csrf_middleware_allows_get_without_token():
    """验证“跨站请求伪造防护中间件允许获取不使用令牌”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client = TestClient(_make_csrf_app())
    resp = client.get("/api/v1/test/read")
    assert resp.status_code == 200


def test_csrf_middleware_exempts_login_local():
    """验证“跨站请求伪造防护中间件该项登录本地”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client = TestClient(_make_csrf_app())
    resp = client.post("/api/v1/auth/login/local")
    assert resp.status_code == 200


def test_csrf_middleware_sets_cookie_on_auth_endpoint():
    """验证“跨站请求伪造防护中间件设置令牌存储该项认证端点”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    client = TestClient(_make_csrf_app())
    resp = client.post("/api/v1/auth/login/local")
    assert CSRF_COOKIE_NAME in resp.cookies


# ── 用户响应边缘情况 ──────────────────────────────────────────


def test_user_response_missing_required_fields():
    """验证“用户响应缺失该项字段”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth.models import UserResponse

    with pytest.raises(ValidationError):
        UserResponse(id="1")  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。

    with pytest.raises(ValidationError):
        UserResponse(id="1", email="a@b.com")  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_user_response_empty_string_role_rejected():
    """验证“用户响应空值字符串该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth.models import UserResponse

    with pytest.raises(ValidationError):
        UserResponse(id="1", email="a@b.com", system_role="")


# ══════════════════════════════════════════════════════════════════════
# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
# ══════════════════════════════════════════════════════════════════════


def _make_auth_app():
    """为“构造认证应用”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    from app.gateway.app import create_app

    return create_app()


def _get_auth_client():
    """为“获取认证客户端”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    return TestClient(_make_auth_app())


def test_api_auth_me_no_cookie_returns_structured_401():
    """验证“接口认证该项该项令牌存储返回结构化该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "not_authenticated"
    assert "message" in body["detail"]


def test_api_auth_me_auth_disabled_returns_synthetic_user(monkeypatch):
    """验证“接口认证该项认证该项返回该项用户”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = _get_auth_client()

    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID

    body = resp.json()
    assert body["id"] == AUTH_DISABLED_USER_ID
    assert body["oauth_provider"] is None


def test_api_auth_me_expired_token_returns_structured_401():
    """验证“接口认证该项过期令牌返回结构化该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    expired = {"sub": "u1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired, _TEST_SECRET, algorithm="HS256")

    client = _get_auth_client()
    client.cookies.set("access_token", token)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "token_expired"


def test_api_auth_me_invalid_sig_returns_structured_401():
    """验证“接口认证该项非法该项返回结构化该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    payload = {"sub": "u1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-key", algorithm="HS256")

    client = _get_auth_client()
    client.cookies.set("access_token", token)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "token_invalid"


def test_api_login_bad_credentials_returns_structured_401():
    """验证“接口登录该项该项返回结构化该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": "nonexistent@test.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "invalid_credentials"


def test_api_login_success_no_token_in_body():
    """验证“接口登录该项该项令牌该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    # 先注册
    client.post(
        "/api/v1/auth/register",
        json={"email": "contract-test@test.com", "password": "securepassword123"},
    )
    # 登录
    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": "contract-test@test.com", "password": "securepassword123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "expires_in" in body
    assert "access_token" not in body
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    assert "access_token" in resp.cookies


def test_api_register_duplicate_returns_structured_400():
    """验证“接口该项重复返回结构化该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    email = "dup-contract-test@test.com"
    # 首先注册
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})
    # 重复
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "AnotherStr0ngPwd!"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["code"] == "email_already_exists"


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def _unique_email(prefix: str) -> str:
    """为“唯一邮箱”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    return f"{prefix}-{secrets.token_hex(4)}@test.com"


def _get_set_cookie_headers(resp) -> list[str]:
    """为“获取该项令牌存储该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    return [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]


def test_register_http_cookie_httponly_true_secure_false():
    """验证“该项超文本传输协议令牌存储该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("http-cookie"), "password": "Tr0ub4dor3a"},
    )
    assert resp.status_code == 201
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "secure" not in cookie_header.lower().replace("samesite", "")


def test_register_https_cookie_httponly_true_secure_true():
    """验证“该项该项令牌存储该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("https-cookie"), "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 201
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "secure" in cookie_header.lower()
    assert "max-age" in cookie_header.lower()


def test_login_https_sets_secure_cookie():
    """验证“登录该项设置该项令牌存储”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    email = _unique_email("https-login")
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})
    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "secure" in cookie_header.lower()


def test_csrf_cookie_secure_on_https():
    """验证“跨站请求伪造防护令牌存储该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-https"), "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 201
    csrf_cookies = [h for h in _get_set_cookie_headers(resp) if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTPS register"
    csrf_header = csrf_cookies[0]
    assert "secure" in csrf_header.lower()
    assert "httponly" not in csrf_header.lower()


def test_csrf_cookie_not_secure_on_http():
    """验证“跨站请求伪造防护令牌存储该项该项该项超文本传输协议”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-http"), "password": "Tr0ub4dor3a"},
    )
    assert resp.status_code == 201
    csrf_cookies = [h for h in _get_set_cookie_headers(resp) if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTP register"
    csrf_header = csrf_cookies[0]
    assert "secure" not in csrf_header.lower().replace("samesite", "")


def test_csrf_cookie_persistent_on_https():
    """验证“跨站请求伪造防护令牌存储该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-persist"), "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 201
    set_cookies = _get_set_cookie_headers(resp)
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTPS register"
    assert "max-age" in csrf_cookies[0].lower(), "csrf_token must be persistent over HTTPS so iOS PWAs don't drop it as a session cookie"
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    assert access_cookies and "max-age" in access_cookies[0].lower()


def test_csrf_cookie_session_only_on_http():
    """验证“跨站请求伪造防护令牌存储会话仅该项超文本传输协议”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-session"), "password": "Tr0ub4dor3a"},
    )
    assert resp.status_code == 201
    csrf_cookies = [h for h in _get_set_cookie_headers(resp) if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTP register"
    assert "max-age" not in csrf_cookies[0].lower()


def test_oidc_callback_csrf_cookie_persistent_on_https():
    """验证“该项该项跨站请求伪造防护令牌存储该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from starlette.requests import Request
    from starlette.responses import Response

    from app.gateway.routers.auth import _set_csrf_cookie

    _setup_config()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/callback/example",
        "headers": [(b"x-forwarded-proto", b"https")],
        "scheme": "http",
        "server": ("internal", 8000),
        "query_string": b"",
    }
    response = Response()
    _set_csrf_cookie(response, Request(scope))
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "csrf_token=" in set_cookie
    assert "secure" in set_cookie
    assert "max-age" in set_cookie
