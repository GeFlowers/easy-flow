"""OIDC（OpenID Connect）认证服务。

提供与供应商无关的 OIDC 发现、授权 URL 生成、令牌交换、ID 令牌验证及用户
信息读取能力。
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWK

logger = logging.getLogger(__name__)

# ── 数据类型 ──────────────────────────────────────────────────────────────

OIDC_DISCOVERY_PATH = "/.well-known/openid-configuration"
METADATA_CACHE_TTL = 300  # 5 minutes
JWKS_CACHE_TTL = 300


@dataclass(frozen=True)
class OIDCMetadata:
    """完成发现后得到的 OIDC 提供者元数据。"""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None
    jwks_uri: str


@dataclass(frozen=True)
class OIDCIdentity:
    """从 OIDC 提供者响应中提取并标准化的身份信息。"""

    provider: str
    subject: str
    email: str
    email_verified: bool
    name: str | None
    claims: dict[str, Any]


class OIDCError(Exception):
    """OIDC 操作的基础异常，其消息可安全用于 API 响应。"""


class OIDCProviderError(OIDCError):
    """OIDC 提供者返回错误，例如 ``access_denied``。"""


class OIDCValidationError(OIDCError):
    """ID 令牌验证失败。"""


class OIDCUserInfoMismatch(OIDCError):
    """UserInfo 的 ``sub`` 与 ID 令牌的 ``sub`` 不匹配。"""


# ── 服务 ──────────────────────────────────────────────────────────────────


class OIDCService:
    """OIDC 认证服务。

    在进程内缓存提供者元数据和 JWKS，并按提供者 ``issuer`` 隔离缓存；构造参数
    可配置两类缓存的存活时间。
    """

    def __init__(
        self,
        metadata_cache_ttl: float = METADATA_CACHE_TTL,
        jwks_cache_ttl: float = JWKS_CACHE_TTL,
    ) -> None:
        """初始化 OIDC HTTP 客户端及提供者元数据、JWKS 缓存。"""
        self._metadata_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._metadata_ttl = metadata_cache_ttl
        self._jwks_ttl = jwks_cache_ttl
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self._http.aclose()

    # ── 发现 ──────────────────────────────────────────────────────────────

    async def discover(self, issuer: str, overrides: dict[str, str | None] | None = None) -> OIDCMetadata:
        """读取并缓存 issuer 的 OIDC 发现元数据，可用 ``overrides`` 覆盖端点。"""
        now = time.time()
        cached = self._metadata_cache.get(issuer)
        if cached and now - cached[0] < self._metadata_ttl:
            return self._metadata_from_dict(cached[1], overrides)

        discovery_url = issuer.rstrip("/") + OIDC_DISCOVERY_PATH
        try:
            resp = await self._http.get(discovery_url)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise OIDCError(f"OIDC discovery failed for issuer {issuer}: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise OIDCError(f"OIDC discovery failed for issuer {issuer}: {exc}") from exc

        discovered_issuer = data.get("issuer")
        if not discovered_issuer:
            raise OIDCError(f"OIDC discovery response from {issuer} is missing the issuer field")

        # 标准要求元数据签发方与配置签发方相等。固定二者的一致性可防止被篡改或
        # 恶意的发现文档把接受的签发方（进而令牌伪造面）引向攻击者指定值。
        if discovered_issuer.rstrip("/") != issuer.rstrip("/"):
            raise OIDCError(f"OIDC discovered issuer '{discovered_issuer}' does not match configured issuer '{issuer}'")

        self._metadata_cache[issuer] = (now, data)
        return self._metadata_from_dict(data, overrides)

    def _metadata_from_dict(self, data: dict[str, Any], overrides: dict[str, str | None] | None) -> OIDCMetadata:
        """由发现字典构建 ``OIDCMetadata``，并应用端点覆盖值。"""
        overrides = overrides or {}
        return OIDCMetadata(
            issuer=data["issuer"],
            authorization_endpoint=overrides.get("authorization_endpoint") or data["authorization_endpoint"],
            token_endpoint=overrides.get("token_endpoint") or data["token_endpoint"],
            userinfo_endpoint=overrides.get("userinfo_endpoint") or data.get("userinfo_endpoint"),
            jwks_uri=overrides.get("jwks_uri") or data["jwks_uri"],
        )

    # ── 授权地址 ─────────────────────────────────────────────────────────

    def build_authorization_url(
        self,
        metadata: OIDCMetadata,
        client_id: str,
        redirect_uri: str,
        scopes: list[str],
        state: str,
        nonce: str | None = None,
        code_challenge: str | None = None,
    ) -> str:
        """构建浏览器应跳转到的 OIDC 提供者授权 URL。"""
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        if nonce:
            params["nonce"] = nonce
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        return f"{metadata.authorization_endpoint}?{urlencode(params)}"

    # ── 令牌交换 ──────────────────────────────────────────────────────────

    async def exchange_code(
        self,
        metadata: OIDCMetadata,
        client_id: str,
        client_secret: str | None,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        auth_method: str = "client_secret_post",
    ) -> dict[str, Any]:
        """在令牌端点使用授权码交换令牌。"""
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        headers: dict[str, str] = {"Accept": "application/json"}

        if auth_method == "client_secret_basic" and client_secret:
            import base64

            creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {creds}"
        elif auth_method == "client_secret_post" and client_secret:
            data["client_secret"] = client_secret

        try:
            resp = await self._http.post(metadata.token_endpoint, data=data, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            body = "unknown"
            try:
                body = exc.response.text[:200]
            except Exception:
                pass
            raise OIDCError(f"Token exchange failed: HTTP {exc.response.status_code} — {body}") from exc
        except httpx.RequestError as exc:
            raise OIDCError(f"Token exchange failed: {exc}") from exc

    # ── 密钥集加载 ───────────────────────────────────────────────────────

    async def _load_jwks(self, jwks_uri: str, force_refresh: bool = False) -> dict[str, Any]:
        """从提供者加载并缓存 JWKS；``force_refresh`` 可在 kid 未命中时跳过缓存。"""
        now = time.time()
        cached = self._jwks_cache.get(jwks_uri)
        if not force_refresh and cached and now - cached[0] < self._jwks_ttl:
            return cached[1]

        try:
            resp = await self._http.get(jwks_uri)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise OIDCError(f"JWKS fetch failed: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise OIDCError(f"JWKS fetch failed: {exc}") from exc

        self._jwks_cache[jwks_uri] = (now, data)
        return data

    async def _resolve_signing_key(
        self,
        jwks_data: dict[str, Any],
        kid: str | None,
        algorithm: str,
        jwks_uri: str,
    ) -> Any | None:
        """在 JWKS 中寻找匹配 ``kid`` 的签名密钥，未找到时返回 ``None``。

        无效 JWK（如算法不匹配的密钥类型）只记录警告，避免单个坏条目中断验证。
        """
        for jwk_dict in jwks_data.get("keys", []):
            if kid and jwk_dict.get("kid") != kid:
                continue
            try:
                jwk = PyJWK(jwk_dict, algorithm=algorithm)
                return jwk.key
            except jwt.PyJWTError as exc:
                logger.warning("Skipping invalid JWK (kid=%s) from %s: %s", kid, jwks_uri, exc)
                if not kid:
                    # 令牌没有密钥标识，继续尝试下一把密钥。
                    continue
                # 已指定密钥标识且当前即该密钥，立即失败。
                raise OIDCValidationError(f"JWK for kid={kid} is invalid: {exc}") from exc
        return None

    # ── 身份令牌验证 ─────────────────────────────────────────────────────

    async def validate_id_token(
        self,
        metadata: OIDCMetadata,
        client_id: str,
        id_token: str,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """验证 ID 令牌并返回声明。

        验证项包括 JWKS 签名、issuer、audience、过期时间、签发时间及可选 nonce。
        """
        jwks_data = await self._load_jwks(metadata.jwks_uri)

        # 使用令牌头部的密钥标识从公开密钥集解析签名密钥。
        jwt_header = jwt.get_unverified_header(id_token)
        kid = jwt_header.get("kid")
        alg = jwt_header.get("alg", "RS256")

        allowed_algorithms = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
        if alg not in allowed_algorithms:
            raise OIDCValidationError(f"ID token uses unsupported algorithm '{alg}'")

        # 解析签名密钥；标识未命中时重新拉取一次公开密钥集，以支持密钥轮换。
        signing_key = await self._resolve_signing_key(jwks_data, kid, alg, metadata.jwks_uri)
        if signing_key is None:
            jwks_data = await self._load_jwks(metadata.jwks_uri, force_refresh=True)
            signing_key = await self._resolve_signing_key(jwks_data, kid, alg, metadata.jwks_uri)
            if signing_key is None:
                raise OIDCValidationError(f"No matching JWK found for kid={kid} after JWKS refresh")

        try:
            claims = jwt.decode(
                id_token,
                key=signing_key,
                algorithms=allowed_algorithms,
                audience=client_id,
                issuer=metadata.issuer,
                options={
                    "verify_exp": True,
                    "verify_iat": True,
                    "require": ["exp", "iss", "sub", "aud"],
                },
            )
        except jwt.ExpiredSignatureError:
            raise OIDCValidationError("ID token has expired")
        except jwt.InvalidIssuerError:
            raise OIDCValidationError("ID token has an invalid issuer")
        except jwt.InvalidAudienceError:
            raise OIDCValidationError("ID token has an invalid audience")
        except jwt.PyJWTError as exc:
            raise OIDCValidationError(f"ID token validation failed: {exc}") from exc

        # 提供预期随机校验值时必须验证它。
        if nonce is not None:
            token_nonce = claims.get("nonce")
            if not token_nonce:
                raise OIDCValidationError("ID token is missing the nonce claim")
            if not _constant_time_compare(nonce, token_nonce):
                raise OIDCValidationError("ID token nonce does not match")

        return claims

    # ── 用户信息 ──────────────────────────────────────────────────────────

    async def fetch_userinfo(self, metadata: OIDCMetadata, access_token: str, expected_sub: str) -> dict[str, Any]:
        """从 UserInfo 端点读取用户信息，并验证其 ``sub`` 与 ID 令牌一致。

        该一致性校验可防止 UserInfo 注入其他用户身份信息。
        """
        if not metadata.userinfo_endpoint:
            return {}

        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = await self._http.get(metadata.userinfo_endpoint, headers=headers)
            resp.raise_for_status()
            userinfo: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise OIDCError(f"UserInfo fetch failed: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise OIDCError(f"UserInfo fetch failed: {exc}") from exc

        if userinfo.get("sub") and userinfo["sub"] != expected_sub:
            raise OIDCUserInfoMismatch("UserInfo sub does not match ID token sub")

        return userinfo

    # ── 回调编排 ──────────────────────────────────────────────────────────

    async def authenticate_callback(
        self,
        provider_id: str,
        metadata: OIDCMetadata,
        client_id: str,
        client_secret: str | None,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        nonce: str | None = None,
        auth_method: str = "client_secret_post",
    ) -> OIDCIdentity:
        """编排完整 OIDC 回调：交换令牌、验证 ID 令牌并读取用户信息。

        返回标准化的 ``OIDCIdentity``。
        """
        token_response = await self.exchange_code(
            metadata=metadata,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            auth_method=auth_method,
        )

        id_token = token_response.get("id_token")
        if not id_token:
            raise OIDCError("Token response is missing id_token")

        access_token = token_response.get("access_token", "")

        claims = await self.validate_id_token(
            metadata=metadata,
            client_id=client_id,
            id_token=id_token,
            nonce=nonce,
        )

        # 当身份令牌未携带邮箱或姓名时，读取用户信息端点补充信息。
        userinfo: dict[str, Any] = {}
        if metadata.userinfo_endpoint and access_token:
            try:
                userinfo = await self.fetch_userinfo(
                    metadata=metadata,
                    access_token=access_token,
                    expected_sub=claims["sub"],
                )
            except OIDCError as exc:
                logger.warning("OIDC userinfo fetch failed (continuing with ID token): %s", exc)

        # 合并用户信息和声明；邮箱以用户信息端点的值优先。
        merged = {**claims, **userinfo}

        email = merged.get("email") or ""
        email_verified = merged.get("email_verified") is True

        return OIDCIdentity(
            provider=provider_id,
            subject=claims["sub"],
            email=email,
            email_verified=email_verified,
            name=merged.get("name"),
            claims=merged,
        )


def _constant_time_compare(a: str, b: str) -> bool:
    """以恒定时间比较字符串，避免泄露匹配位置。"""
    return secrets.compare_digest(a, b)
