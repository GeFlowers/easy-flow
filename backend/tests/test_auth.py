"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import bcrypt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.gateway.auth import create_access_token, decode_token, hash_password, verify_password
from app.gateway.auth.models import User
from app.gateway.auth.password import needs_rehash
from app.gateway.authz import (
    AuthContext,
    Permissions,
    get_auth_context,
    require_auth,
    require_permission,
)

# ── 密码哈希 ────────────────────────────────────────────────────────


def test_hash_password_and_verify():
    """验证“该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    password = "s3cr3tP@ssw0rd!"
    hashed = hash_password(password)
    assert hashed != password
    assert hashed.startswith("$dfv2$")
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_hash_password_different_each_time():
    """验证“该项该项不同该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    password = "testpassword"
    h1 = hash_password(password)
    h2 = hash_password(password)
    assert h1 != h2  # 不同的盐
    # 但都验证正确
    assert verify_password(password, h1) is True
    assert verify_password(password, h2) is True


def test_verify_password_rejects_empty():
    """验证“该项该项拒绝空值”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    hashed = hash_password("nonempty")
    assert verify_password("", hashed) is False


def test_hash_produces_v2_prefix():
    """验证“该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    hashed = hash_password("anypassword123")
    assert hashed.startswith("$dfv2$")


def test_verify_v1_prefixed_hash():
    """验证“该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    password = "legacyP@ssw0rd"
    raw_bcrypt = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    v1_hash = f"$dfv1${raw_bcrypt}"
    assert verify_password(password, v1_hash) is True
    assert verify_password("wrong", v1_hash) is False


def test_verify_bare_bcrypt_hash():
    """验证“该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    password = "oldstyleP@ss"
    raw_bcrypt = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    assert verify_password(password, raw_bcrypt) is True
    assert verify_password("wrong", raw_bcrypt) is False


def test_needs_rehash_returns_false_for_v2():
    """验证“该项该项返回该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    hashed = hash_password("something")
    assert needs_rehash(hashed) is False


def test_needs_rehash_returns_true_for_v1():
    """验证“该项该项返回该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    raw = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8")
    assert needs_rehash(f"$dfv1${raw}") is True


def test_needs_rehash_returns_true_for_bare_bcrypt():
    """验证“该项该项返回该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    raw = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8")
    assert needs_rehash(raw) is True


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_create_and_decode_token():
    """验证“创建该项解码令牌”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user_id = str(uuid4())
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    import os

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(user_id)
    assert isinstance(token, str)

    payload = decode_token(token)
    assert payload is not None
    assert payload.sub == user_id


def test_decode_token_expired():
    """验证“解码令牌过期”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth.errors import TokenError

    user_id = str(uuid4())
    # 创建立即过期的令牌
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))
    payload = decode_token(token)
    assert payload == TokenError.EXPIRED


def test_decode_token_invalid():
    """验证“解码令牌非法”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.auth.errors import TokenError

    assert isinstance(decode_token("not.a.valid.token"), TokenError)
    assert isinstance(decode_token(""), TokenError)
    assert isinstance(decode_token("completely-wrong"), TokenError)


def test_create_token_custom_expiry():
    """验证“创建令牌该项有效期”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user_id = str(uuid4())
    token = create_access_token(user_id, expires_delta=timedelta(hours=1))
    payload = decode_token(token)
    assert payload is not None
    assert payload.sub == user_id


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_auth_context_unauthenticated():
    """验证“认证上下文该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    ctx = AuthContext(user=None, permissions=[])
    assert ctx.is_authenticated is False
    assert ctx.has_permission("threads", "read") is False


def test_auth_context_authenticated_no_perms():
    """验证“认证上下文该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    ctx = AuthContext(user=user, permissions=[])
    assert ctx.is_authenticated is True
    assert ctx.has_permission("threads", "read") is False


def test_auth_context_has_permission():
    """验证“认证上下文该项权限”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    perms = [Permissions.THREADS_READ, Permissions.THREADS_WRITE]
    ctx = AuthContext(user=user, permissions=perms)
    assert ctx.has_permission("threads", "read") is True
    assert ctx.has_permission("threads", "write") is True
    assert ctx.has_permission("threads", "delete") is False
    assert ctx.has_permission("runs", "read") is False


def test_auth_context_require_user_raises():
    """验证“认证上下文要求用户抛出”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    ctx = AuthContext(user=None, permissions=[])
    with pytest.raises(HTTPException) as exc_info:
        ctx.require_user()
    assert exc_info.value.status_code == 401


def test_auth_context_require_user_returns_user():
    """验证“认证上下文要求用户返回用户”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    ctx = AuthContext(user=user, permissions=[])
    returned = ctx.require_user()
    assert returned == user


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_get_auth_context_not_set():
    """验证“获取认证上下文该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    mock_request = MagicMock()
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    mock_request.state = MagicMock()
    del mock_request.state.auth
    assert get_auth_context(mock_request) is None


def test_get_auth_context_set():
    """验证“获取认证上下文该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    ctx = AuthContext(user=user, permissions=[Permissions.THREADS_READ])

    mock_request = MagicMock()
    mock_request.state.auth = ctx

    assert get_auth_context(mock_request) == ctx


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_require_auth_sets_auth_context():
    """验证“要求认证设置认证上下文”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from fastapi import Request

    app = FastAPI()

    @app.get("/test")
    @require_auth
    async def endpoint(request: Request):
        """为“端点”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        ctx = get_auth_context(request)
        return {"authenticated": ctx.is_authenticated}

    with TestClient(app) as client:
        # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        response = client.get("/test")
        assert response.status_code == 401


def test_require_auth_requires_request_param():
    """验证“要求认证该项请求参数”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio

    @require_auth
    async def bad_endpoint():  # 缺少“请求”参数
        """为“该项端点”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        pass

    with pytest.raises(ValueError, match="require_auth decorator requires 'request' parameter"):
        asyncio.run(bad_endpoint())


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_require_permission_requires_auth():
    """验证“要求权限该项认证”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from fastapi import Request

    app = FastAPI()

    @app.get("/test")
    @require_permission("threads", "read")
    async def endpoint(request: Request):
        """为“端点”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]


def test_require_permission_denies_wrong_permission():
    """验证“要求权限该项该项权限”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from fastapi import Request

    app = FastAPI()
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")

    @app.get("/test")
    @require_permission("threads", "delete")
    async def endpoint(request: Request):
        """为“端点”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    mock_auth = AuthContext(user=user, permissions=[Permissions.THREADS_READ])

    with patch("app.gateway.authz._authenticate", return_value=mock_auth):
        with TestClient(app) as client:
            response = client.get("/test")
            assert response.status_code == 403
            assert "Permission denied" in response.json()["detail"]


def _make_internal_owner_check_app():
    """为“构造内部所有者该项应用”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    import asyncio

    from fastapi import Request
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore

    app = FastAPI()
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(thread_store.create("alice-thread", user_id="alice"))
    app.state.thread_store = thread_store

    @app.get("/threads/{thread_id}")
    @require_permission("threads", "read", owner_check=True)
    async def endpoint(thread_id: str, request: Request):
        """为“端点”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return {"ok": True}

    return app


def _internal_auth_context() -> AuthContext:
    """为“内部认证上下文”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    from types import SimpleNamespace

    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user = SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)
    return AuthContext(user=user, permissions=[Permissions.THREADS_READ])


def test_require_permission_internal_role_scoped_by_owner_header():
    """验证“要求权限内部该项该项该项所有者标头”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    app = _make_internal_owner_check_app()
    with patch("app.gateway.authz._authenticate", return_value=_internal_auth_context()):
        with TestClient(app) as client:
            response = client.get(
                "/threads/alice-thread",
                headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "alice"},
            )
    assert response.status_code == 200


def test_require_permission_internal_role_denied_for_other_owner():
    """验证“要求权限内部该项该项该项该项所有者”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    app = _make_internal_owner_check_app()
    with patch("app.gateway.authz._authenticate", return_value=_internal_auth_context()):
        with TestClient(app) as client:
            response = client.get(
                "/threads/alice-thread",
                headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "mallory"},
            )
    assert response.status_code == 404


def test_require_permission_internal_role_without_header_is_scoped_to_internal_user():
    """验证“要求权限内部该项不使用标头该项该项该项内部用户”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    app = _make_internal_owner_check_app()
    with patch("app.gateway.authz._authenticate", return_value=_internal_auth_context()):
        with TestClient(app) as client:
            response = client.get("/threads/alice-thread")
    assert response.status_code == 404


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


# ── 用户模型字段 ──────────────────────────────────────────────────────


def test_user_model_has_needs_setup_default_false():
    """验证“用户该项该项该项设置默认值该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user = User(email="test@example.com", password_hash="hash")
    assert user.needs_setup is False


def test_user_model_has_token_version_default_zero():
    """验证“用户该项该项令牌版本默认值该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user = User(email="test@example.com", password_hash="hash")
    assert user.token_version == 0


def test_user_model_needs_setup_true():
    """验证“用户该项该项设置该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    user = User(email="admin@example.com", password_hash="hash", needs_setup=True)
    assert user.needs_setup is True


def test_sqlite_round_trip_new_fields():
    """验证“轻量数据库该项该项新的字段”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio
    import tempfile

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        from deerflow.persistence.engine import (
            close_engine,
            get_session_factory,
            init_engine,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"sqlite+aiosqlite:///{tmpdir}/scratch.db"
            await init_engine("sqlite", url=url, sqlite_dir=tmpdir)
            try:
                repo = SQLiteUserRepository(get_session_factory())
                user = User(
                    email="setup@test.com",
                    password_hash="fakehash",
                    system_role="admin",
                    needs_setup=True,
                    token_version=3,
                )
                created = await repo.create_user(user)
                assert created.needs_setup is True
                assert created.token_version == 3

                fetched = await repo.get_user_by_email("setup@test.com")
                assert fetched is not None
                assert fetched.needs_setup is True
                assert fetched.token_version == 3

                fetched.needs_setup = False
                fetched.token_version = 4
                await repo.update_user(fetched)
                refetched = await repo.get_user_by_id(str(fetched.id))
                assert refetched is not None
                assert refetched.needs_setup is False
                assert refetched.token_version == 4
            finally:
                await close_engine()

    asyncio.run(_run())


def test_update_user_raises_when_row_concurrently_deleted(tmp_path):
    """验证“更新用户抛出当记录该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio
    import tempfile

    from app.gateway.auth.repositories.base import UserNotFoundError
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        """在临时数据库中复现并发删除，使仓储更新路径必须传播用户不存在错误并完成引擎清理。"""
        from deerflow.persistence.engine import (
            close_engine,
            get_session_factory,
            init_engine,
        )
        from deerflow.persistence.user.model import UserRow

        with tempfile.TemporaryDirectory() as d:
            url = f"sqlite+aiosqlite:///{d}/scratch.db"
            await init_engine("sqlite", url=url, sqlite_dir=d)
            try:
                sf = get_session_factory()
                repo = SQLiteUserRepository(sf)
                user = User(
                    email="ghost@test.com",
                    password_hash="fakehash",
                    system_role="user",
                )
                created = await repo.create_user(user)

                # 通过删除行来模拟“行在我们下面消失”
                # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
                async with sf() as session:
                    row = await session.get(UserRow, str(created.id))
                    assert row is not None
                    await session.delete(row)
                    await session.commit()

                created.needs_setup = True
                with pytest.raises(UserNotFoundError):
                    await repo.update_user(created)
            finally:
                await close_engine()

    asyncio.run(_run())


# ── 令牌版本控制 ────────────────────────────────────────────────────────


def test_jwt_encodes_ver():
    """验证“令牌该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import os

    from app.gateway.auth.errors import TokenError

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(str(uuid4()), token_version=3)
    payload = decode_token(token)
    assert not isinstance(payload, TokenError)
    assert payload.ver == 3


def test_jwt_default_ver_zero():
    """验证“令牌默认值该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import os

    from app.gateway.auth.errors import TokenError

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(str(uuid4()))
    payload = decode_token(token)
    assert not isinstance(payload, TokenError)
    assert payload.ver == 0


def test_token_version_mismatch_rejects():
    """验证“令牌版本该项拒绝”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio
    import os

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"

    user_id = str(uuid4())
    token = create_access_token(user_id, token_version=0)

    mock_user = User(id=user_id, email="test@example.com", password_hash="hash", token_version=1)

    mock_request = MagicMock()
    mock_request.cookies = {"access_token": token}

    with patch("app.gateway.deps.get_local_provider") as mock_provider_fn:
        mock_provider = MagicMock()
        mock_provider.get_user = AsyncMock(return_value=mock_user)
        mock_provider_fn.return_value = mock_provider

        from app.gateway.deps import get_current_user_from_request

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_user_from_request(mock_request))
        assert exc_info.value.status_code == 401
        assert "revoked" in str(exc_info.value.detail).lower()


# ── 更改密码扩展 ──────────────────────────────────────────────


def test_change_password_request_accepts_new_email():
    """验证“变化该项请求该项新的邮箱”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import ChangePasswordRequest

    req = ChangePasswordRequest(
        current_password="old",
        new_password="newpassword",
        new_email="new@example.com",
    )
    assert req.new_email == "new@example.com"


def test_change_password_request_new_email_optional():
    """验证“变化该项请求新的邮箱该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import ChangePasswordRequest

    req = ChangePasswordRequest(current_password="old", new_password="newpassword")
    assert req.new_email is None


def test_login_response_includes_needs_setup():
    """验证“登录响应该项该项设置”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import LoginResponse

    resp = LoginResponse(expires_in=3600, needs_setup=True)
    assert resp.needs_setup is True
    resp2 = LoginResponse(expires_in=3600)
    assert resp2.needs_setup is False


# ── 速率限制 ──────────────────────────────────────────────────────────


def test_rate_limiter_allows_under_limit():
    """验证“该项该项允许该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import _check_rate_limit, _login_attempts

    _login_attempts.clear()
    _check_rate_limit("192.168.1.1")  # 不应提高


def test_rate_limiter_blocks_after_max_failures():
    """验证“该项该项该项该项最大该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import _check_rate_limit, _login_attempts, _record_login_failure

    _login_attempts.clear()
    ip = "10.0.0.1"
    for _ in range(5):
        _record_login_failure(ip)
    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(ip)
    assert exc_info.value.status_code == 429


def test_rate_limiter_resets_on_success():
    """验证“该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import _check_rate_limit, _login_attempts, _record_login_failure, _record_login_success

    _login_attempts.clear()
    ip = "10.0.0.2"
    for _ in range(4):
        _record_login_failure(ip)
    _record_login_success(ip)
    _check_rate_limit(ip)  # 不应提高


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_get_client_ip_direct_connection_no_proxy(monkeypatch):
    """验证“获取客户端网络地址该项连接该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "203.0.113.42"
    req.headers = {}
    assert _get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_x_real_ip_ignored_when_no_trusted_proxy(monkeypatch):
    """验证“获取客户端网络地址该项该项网络地址该项当该项可信该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "127.0.0.1"


def test_get_client_ip_x_real_ip_honored_from_trusted_proxy(monkeypatch):
    """验证“获取客户端网络地址该项该项网络地址该项该项可信该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "10.5.6.7"  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_x_real_ip_rejected_from_untrusted_peer(monkeypatch):
    """验证“获取客户端网络地址该项该项网络地址该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "8.8.8.8"  # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    req.headers = {"x-real-ip": "203.0.113.42"}  # 客户端试图欺骗
    assert _get_client_ip(req) == "8.8.8.8"


def test_get_client_ip_xff_never_honored(monkeypatch):
    """验证“获取客户端网络地址该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers = {"x-forwarded-for": "198.51.100.5"}  # 未提供真实网络地址标头，用于固定回退到客户端地址的边界。
    assert _get_client_ip(req) == "10.0.0.1"


def test_get_client_ip_invalid_trusted_proxy_entry_skipped(monkeypatch, caplog):
    """验证“获取客户端网络地址非法可信该项条目该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "not-an-ip,10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "10.5.6.7"
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "203.0.113.42"  # 有效条目仍然有效


def test_get_client_ip_no_client_returns_unknown(monkeypatch):
    """验证“获取客户端网络地址该项客户端返回该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client = None
    req.headers = {}
    assert _get_client_ip(req) == "unknown"


# ── 通用密码阻止列表 ────────────────────────────────────────────────


def test_register_rejects_literal_password():
    """验证“该项拒绝该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from pydantic import ValidationError

    from app.gateway.routers.auth import RegisterRequest

    with pytest.raises(ValidationError) as exc:
        RegisterRequest(email="x@example.com", password="password")
    assert "too common" in str(exc.value)


def test_register_rejects_common_password_case_insensitive():
    """验证“该项拒绝该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from pydantic import ValidationError

    from app.gateway.routers.auth import RegisterRequest

    for variant in ["PASSWORD", "Password1", "qwerty123", "letmein1"]:
        with pytest.raises(ValidationError):
            RegisterRequest(email="x@example.com", password=variant)


def test_register_accepts_strong_password():
    """验证“该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import RegisterRequest

    req = RegisterRequest(email="x@example.com", password="Tr0ub4dor&3-Horse")
    assert req.password == "Tr0ub4dor&3-Horse"


def test_change_password_rejects_common_password():
    """验证“变化该项拒绝该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from pydantic import ValidationError

    from app.gateway.routers.auth import ChangePasswordRequest

    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="anything", new_password="iloveyou")


def test_password_blocklist_keeps_short_passwords_for_length_check():
    """验证“该项该项保留该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from pydantic import ValidationError

    from app.gateway.routers.auth import RegisterRequest

    with pytest.raises(ValidationError) as exc:
        RegisterRequest(email="x@example.com", password="abc")
    # 应触发长度检查，而不是阻止列表
    assert "at least 8 characters" in str(exc.value)


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def test_missing_jwt_secret_generates_ephemeral(monkeypatch, caplog):
    """验证“缺失令牌密钥该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import logging

    import app.gateway.auth.config as config_module

    config_module._auth_config = None
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    with caplog.at_level(logging.WARNING):
        config = config_module.get_auth_config()

    assert config.jwt_secret  # 非空短暂秘密
    assert any("AUTH_JWT_SECRET" in msg for msg in caplog.messages)

    # 清理
    config_module._auth_config = None


# ── 登录时自动重新哈希──────────────────────────────────────────────────


def test_authenticate_auto_rehashes_legacy_hash():
    """验证“该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio

    from app.gateway.auth.local_provider import LocalAuthProvider

    password = "rehashTest123"

    user = User(
        id=uuid4(),
        email="rehash@test.com",
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
    )

    mock_repo = MagicMock()
    mock_repo.get_user_by_email = AsyncMock(return_value=user)
    mock_repo.update_user = AsyncMock(return_value=user)

    provider = LocalAuthProvider(mock_repo)

    result = asyncio.run(provider.authenticate({"email": "rehash@test.com", "password": password}))
    assert result is not None
    assert result.password_hash.startswith("$dfv2$")
    mock_repo.update_user.assert_called_once()


def test_authenticate_skips_rehash_for_v2_hash():
    """验证“该项该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import asyncio

    from app.gateway.auth.local_provider import LocalAuthProvider

    password = "alreadyv2Pass!"

    user = User(
        id=uuid4(),
        email="v2@test.com",
        password_hash=hash_password(password),
    )

    mock_repo = MagicMock()
    mock_repo.get_user_by_email = AsyncMock(return_value=user)
    mock_repo.update_user = AsyncMock(return_value=user)

    provider = LocalAuthProvider(mock_repo)

    result = asyncio.run(provider.authenticate({"email": "v2@test.com", "password": password}))
    assert result is not None
    mock_repo.update_user.assert_not_called()


def test_validate_next_param_rejects_colon_paths():
    """验证“校验下一个参数拒绝该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    from app.gateway.routers.auth import validate_next_param

    assert validate_next_param("/workspace") == "/workspace"
    assert validate_next_param("/:evil") is None
