"""验证 OIDC 账户绑定、令牌校验、发现文档及回调重定向的安全边界。"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCError, OIDCIdentity, OIDCMetadata, OIDCService, OIDCValidationError
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from deerflow.config.auth_config import OIDCProviderConfig


def _provider_config(**overrides):
    """创建可由调用方覆盖字段的 OIDC 提供方配置测试数据。"""
    return OIDCProviderConfig(
        display_name="Test SSO",
        issuer="https://issuer.example.com",
        client_id="deer-flow",
        **overrides,
    )


def _identity(**overrides):
    """创建可由调用方覆盖声明字段的默认 OIDC 身份对象。"""
    values = {
        "provider": "keycloak",
        "subject": "oidc-subject",
        "email": "user@example.com",
        "email_verified": True,
        "name": "Test User",
        "claims": {},
    }
    values.update(overrides)
    return OIDCIdentity(**values)


@pytest.mark.asyncio
async def test_oidc_existing_local_account_blocks_sso_login_even_when_unverified():
    """验证未验证邮箱不能借助 SSO 绑定到已有本地密码账户。"""
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(
                require_verified_email=False,
                auto_create_users=False,
            ),
            identity=_identity(email_verified=False),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409
    local_provider.update_user.assert_not_called()


@pytest.mark.asyncio
async def test_oidc_existing_local_account_blocks_sso_login_even_when_verified():
    """验证已验证邮箱同样不能借助 SSO 绑定到已有本地密码账户。"""
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(auto_create_users=False),
            identity=_identity(subject="verified-subject"),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409
    local_provider.update_user.assert_not_called()
    local_provider.create_oauth_user.assert_not_called()


@pytest.mark.asyncio
async def test_oidc_auto_create_assigns_admin_role_from_configured_email():
    """验证自动创建账户时，配置中大小写不同的管理员邮箱仍获管理员角色。"""
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    created_user = User(
        email="admin@example.com",
        password_hash=None,
        system_role="admin",
        oauth_provider="keycloak",
        oauth_id="admin-subject",
    )
    local_provider.create_oauth_user.return_value = created_user

    result = await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(admin_emails=["ADMIN@example.com"]),
        identity=_identity(subject="admin-subject", email="admin@example.com"),
        local_provider=local_provider,
    )

    assert result == {"user": created_user, "created": True}
    local_provider.create_oauth_user.assert_awaited_once_with(
        email="admin@example.com",
        oauth_provider="keycloak",
        oauth_id="admin-subject",
        system_role="admin",
    )


@pytest.mark.asyncio
async def test_oidc_validate_id_token_refreshes_jwks_once_on_kid_miss(monkeypatch):
    """验证首次按 kid 查无签名密钥后仅强制刷新 JWKS 一次并重试。"""
    service = OIDCService()
    metadata = OIDCMetadata(
        issuer="https://issuer.example.com",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint=None,
        jwks_uri="https://issuer.example.com/jwks",
    )
    load_calls = []
    resolve_results = [None, "signing-key"]

    async def load_jwks(jwks_uri, force_refresh=False):
        """记录 JWKS 加载是否被强制刷新，并返回空密钥集。"""
        load_calls.append(force_refresh)
        return {"keys": []}

    async def resolve_signing_key(jwks_data, kid, algorithm, jwks_uri):
        """依次模拟未命中和命中签名密钥，以驱动刷新后的重试路径。"""
        return resolve_results.pop(0)

    monkeypatch.setattr(service, "_load_jwks", load_jwks)
    monkeypatch.setattr(service, "_resolve_signing_key", resolve_signing_key)
    monkeypatch.setattr("app.gateway.auth.oidc.jwt.get_unverified_header", lambda token: {"kid": "new-kid", "alg": "RS256"})
    monkeypatch.setattr(
        "app.gateway.auth.oidc.jwt.decode",
        lambda *args, **kwargs: {"iss": metadata.issuer, "sub": "subject", "aud": "deer-flow", "exp": 9999999999},
    )

    claims = await service.validate_id_token(metadata, "deer-flow", "id-token")

    assert claims["sub"] == "subject"
    assert load_calls == [False, True]
    await service.close()


@pytest.mark.asyncio
async def test_oidc_validate_id_token_rejects_hmac_algorithms(monkeypatch):
    """验证令牌头声明 HMAC 算法时，在解析密钥或解码前即被拒绝。"""
    service = OIDCService()
    metadata = OIDCMetadata(
        issuer="https://issuer.example.com",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint=None,
        jwks_uri="https://issuer.example.com/jwks",
    )

    async def load_jwks(jwks_uri, force_refresh=False):
        """返回包含对称密钥的 JWKS，确认算法白名单不会依赖密钥类型放行。"""
        return {"keys": [{"kid": "kid", "kty": "oct", "k": "secret"}]}

    async def resolve_signing_key(jwks_data, kid, algorithm, jwks_uri):
        """返回对称密钥；若算法校验失效，此替身将成为后续解码输入。"""
        return "secret"

    def decode(*args, **kwargs):
        """断言传给解码器的算法列表不含 HS256，并模拟校验失败。"""
        assert "HS256" not in kwargs["algorithms"]
        raise OIDCValidationError("HMAC algorithms must not be accepted")

    monkeypatch.setattr(service, "_load_jwks", load_jwks)
    monkeypatch.setattr(service, "_resolve_signing_key", resolve_signing_key)
    monkeypatch.setattr("app.gateway.auth.oidc.jwt.get_unverified_header", lambda token: {"kid": "kid", "alg": "HS256"})
    monkeypatch.setattr("app.gateway.auth.oidc.jwt.decode", decode)

    with pytest.raises(OIDCValidationError, match="unsupported algorithm"):
        await service.validate_id_token(metadata, "deer-flow", "id-token")

    await service.close()


@pytest.mark.asyncio
async def test_oidc_existing_account_lookup_uses_normalized_email():
    """验证查找已有账户前会将混合大小写的 OIDC 邮箱规范化。"""
    local_user = User(email="user@example.com", password_hash="hash")
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = local_user

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(auto_create_users=False),
            identity=_identity(email="User@Example.COM"),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409
    local_provider.get_user_by_email.assert_awaited_once_with("user@example.com")


@pytest.mark.asyncio
async def test_oidc_auto_create_uses_normalized_email():
    """验证自动创建 OIDC 账户时将混合大小写邮箱以规范化形式持久化。"""
    local_provider = AsyncMock()
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    created_user = User(email="user@example.com", password_hash=None, oauth_provider="keycloak", oauth_id="subject")
    local_provider.create_oauth_user.return_value = created_user

    await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(),
        identity=_identity(subject="subject", email="User@Example.COM"),
        local_provider=local_provider,
    )

    local_provider.create_oauth_user.assert_awaited_once_with(
        email="user@example.com",
        oauth_provider="keycloak",
        oauth_id="subject",
        system_role="user",
    )


@pytest.mark.asyncio
async def test_oidc_metadata_from_dict_accepts_missing_overrides():
    """验证发现文档未提供可选覆盖项时仍可构造完整 OIDC 元数据。"""
    service = OIDCService()

    metadata = service._metadata_from_dict(
        {
            "issuer": "https://issuer.example.com",
            "authorization_endpoint": "https://issuer.example.com/auth",
            "token_endpoint": "https://issuer.example.com/token",
            "userinfo_endpoint": "https://issuer.example.com/userinfo",
            "jwks_uri": "https://issuer.example.com/jwks",
        },
        None,
    )

    assert metadata.jwks_uri == "https://issuer.example.com/jwks"
    await service.close()


@pytest.mark.asyncio
async def test_oidc_authenticate_callback_treats_string_false_email_verified_as_unverified(monkeypatch):
    """验证回调中的字符串声明值 false 会被解释为未验证邮箱。"""
    service = OIDCService()
    metadata = OIDCMetadata(
        issuer="https://issuer.example.com",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        userinfo_endpoint=None,
        jwks_uri="https://issuer.example.com/jwks",
    )

    async def exchange_code(**kwargs):
        """模拟授权码兑换，仅返回供后续校验使用的 ID 令牌。"""
        return {"id_token": "id-token"}

    async def validate_id_token(**kwargs):
        """返回 email_verified 为字符串 false 的已校验声明。"""
        return {"sub": "subject", "email": "user@example.com", "email_verified": "false"}

    monkeypatch.setattr(service, "exchange_code", exchange_code)
    monkeypatch.setattr(service, "validate_id_token", validate_id_token)

    identity = await service.authenticate_callback(
        provider_id="keycloak",
        metadata=metadata,
        client_id="deer-flow",
        client_secret=None,
        code="code",
        redirect_uri="https://app.example.com/callback",
    )

    assert identity.email_verified is False
    await service.close()


@pytest.mark.asyncio
async def test_oidc_provision_recovers_existing_user_on_create_race():
    """验证创建竞争失败后重新查到同一 OAuth 身份时复用已有用户。"""
    created_user = User(email="user@example.com", password_hash=None, oauth_provider="keycloak", oauth_id="subject")
    local_provider = AsyncMock()
    # 首次按 OAuth 身份查找未命中；创建竞争抛错后，二次查找命中已有用户。
    local_provider.get_user_by_oauth.side_effect = [None, created_user]
    local_provider.get_user_by_email.return_value = None
    local_provider.create_oauth_user.side_effect = ValueError("Email already registered: user@example.com")

    result = await get_or_provision_oidc_user(
        provider_id="keycloak",
        provider_config=_provider_config(),
        identity=_identity(subject="subject"),
        local_provider=local_provider,
    )

    assert result == {"user": created_user, "created": False}
    assert local_provider.get_user_by_oauth.await_count == 2


@pytest.mark.asyncio
async def test_oidc_provision_create_race_on_email_only_raises_409():
    """验证创建竞争仅发生邮箱冲突且无同一 OAuth 身份时返回 409。"""
    local_provider = AsyncMock()
    # 竞争前后均不存在 OAuth 绑定，表示邮箱冲突而非同一 subject 的重复创建。
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    local_provider.create_oauth_user.side_effect = ValueError("Email already registered: user@example.com")

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user(
            provider_id="keycloak",
            provider_config=_provider_config(),
            identity=_identity(subject="subject"),
            local_provider=local_provider,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_oidc_discover_rejects_mismatched_issuer(monkeypatch):
    """验证发现文档中的 issuer 与配置 issuer 不一致时拒绝登录。"""
    service = OIDCService()

    class _Resp:
        """模拟返回 issuer 不匹配的发现文档响应。"""
        def raise_for_status(self):
            """模拟成功的 HTTP 状态检查。"""
            return None

        def json(self):
            """返回 issuer 被篡改的 OIDC 发现文档。"""
            return {
                "issuer": "https://evil.example.com",
                "authorization_endpoint": "https://issuer.example.com/auth",
                "token_endpoint": "https://issuer.example.com/token",
                "jwks_uri": "https://issuer.example.com/jwks",
            }

    async def fake_get(url):
        """替代 HTTP GET，始终返回当前测试的发现文档响应。"""
        return _Resp()

    monkeypatch.setattr(service._http, "get", fake_get)

    with pytest.raises(OIDCError, match="does not match configured issuer"):
        await service.discover("https://issuer.example.com")

    await service.close()


@pytest.mark.asyncio
async def test_oidc_discover_accepts_issuer_with_trailing_slash_difference(monkeypatch):
    """验证 issuer 仅尾部斜杠不同的发现文档可被接受。"""
    service = OIDCService()

    class _Resp:
        """模拟返回尾部斜杠不同 issuer 的发现文档响应。"""
        def raise_for_status(self):
            """模拟成功的 HTTP 状态检查。"""
            return None

        def json(self):
            """返回 issuer 带尾部斜杠的 OIDC 发现文档。"""
            return {
                "issuer": "https://issuer.example.com/",
                "authorization_endpoint": "https://issuer.example.com/auth",
                "token_endpoint": "https://issuer.example.com/token",
                "jwks_uri": "https://issuer.example.com/jwks",
            }

    async def fake_get(url):
        """替代 HTTP GET，始终返回当前测试的发现文档响应。"""
        return _Resp()

    monkeypatch.setattr(service._http, "get", fake_get)

    metadata = await service.discover("https://issuer.example.com")

    assert metadata.issuer == "https://issuer.example.com/"
    await service.close()


def _redirect_request(headers: dict, scheme: str = "http", netloc: str = "localhost:8001"):
    """构造带指定请求头、协议和主机名的重定向请求替身。"""
    from unittest.mock import MagicMock

    req = MagicMock()
    req.headers = headers
    req.url.scheme = scheme
    req.url.netloc = netloc
    return req


def test_oidc_redirect_uri_prefers_configured_value():
    """验证配置了回调地址时忽略请求中的不可信主机名。"""
    from app.gateway.routers.auth import _resolve_oidc_redirect_uri

    cfg = _provider_config(redirect_uri="https://app.example.com/api/v1/auth/callback/keycloak")
    req = _redirect_request({"host": "attacker.example.com"})

    assert _resolve_oidc_redirect_uri(req, "keycloak", cfg) == "https://app.example.com/api/v1/auth/callback/keycloak"


def test_oidc_redirect_uri_fallback_uses_forwarded_headers_not_raw_host():
    """验证未配置回调地址时优先使用代理写入的转发请求头。"""
    from app.gateway.routers.auth import _resolve_oidc_redirect_uri

    cfg = _provider_config()
    # 原始主机字段可被攻击者控制，代理声明的转发字段必须优先。
    req = _redirect_request(
        {
            "host": "attacker.example.com",
            "x-forwarded-host": "app.example.com",
            "x-forwarded-proto": "https",
        }
    )

    result = _resolve_oidc_redirect_uri(req, "keycloak", cfg)

    assert result == "https://app.example.com/api/v1/auth/callback/keycloak"


def test_oidc_redirect_uri_fallback_plain_host_when_no_proxy_headers():
    """验证没有转发请求头时以普通主机字段和原始协议生成回调地址。"""
    from app.gateway.routers.auth import _resolve_oidc_redirect_uri

    cfg = _provider_config()
    req = _redirect_request({"host": "localhost:8001"})

    result = _resolve_oidc_redirect_uri(req, "keycloak", cfg)

    assert result == "http://localhost:8001/api/v1/auth/callback/keycloak"
