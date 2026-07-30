"""通过签名 HttpOnly Cookie 管理 OIDC 状态。

将 OIDC state、nonce 和 PKCE 校验器存入短生命周期签名 Cookie，而非服务器端
存储，从而保持无状态并兼容不依赖 Redis 的多工作进程部署。
"""

from __future__ import annotations

import secrets
import time

import jwt
from fastapi import Request, Response
from pydantic import BaseModel, Field

from app.gateway.auth.config import get_auth_config
from app.gateway.csrf_middleware import is_secure_request

OIDC_STATE_COOKIE_PREFIX = "df_oidc_state_"
OIDC_STATE_MAX_AGE = 300  # 5 minutes
OIDC_STATE_BYTES = 32
OIDC_NONCE_BYTES = 16
OIDC_CODE_VERIFIER_BYTES = 32


class OIDCStatePayload(BaseModel):
    """存放在已签名 OIDC 状态 Cookie 中的负载。"""

    provider: str = Field(description="OIDC provider ID (must match the state cookie)")  # noqa: E501
    state: str = Field(description="Cryptographically random state value — compared in constant time with the query param")  # noqa: E501
    nonce: str | None = Field(default=None, description="OIDC nonce, verified against the ID token nonce claim")
    code_verifier: str | None = Field(default=None, description="PKCE code verifier, sent during token exchange")
    next_path: str = Field(default="/workspace", description="Redirect target after successful auth")
    issued_at: float = Field(default_factory=time.time, description="Unix timestamp of cookie creation")


def _sign_state_payload(payload: OIDCStatePayload) -> str:
    """使用 JWT 密钥签名状态负载，防止 Cookie 内容遭篡改。"""
    secret = get_auth_config().jwt_secret
    return jwt.encode(payload.model_dump(), secret, algorithm="HS256")


def _verify_state_signed(signed: str, max_age: int = OIDC_STATE_MAX_AGE) -> OIDCStatePayload | None:
    """验证已签名状态负载；无效或过期时返回 ``None``。"""
    secret = get_auth_config().jwt_secret
    try:
        decoded = jwt.decode(signed, secret, algorithms=["HS256"])
        payload = OIDCStatePayload(**decoded)
        if time.time() - payload.issued_at > max_age:
            return None
        return payload
    except jwt.PyJWTError:
        return None


def generate_oidc_state() -> str:
    """生成密码学安全的随机 state 字符串。"""
    return secrets.token_urlsafe(OIDC_STATE_BYTES)


def generate_nonce() -> str:
    """生成供 ID 令牌校验使用的密码学安全随机 nonce。"""
    return secrets.token_urlsafe(OIDC_NONCE_BYTES)


def generate_code_verifier() -> str:
    """生成 PKCE code verifier 随机字符串。"""
    return secrets.token_urlsafe(OIDC_CODE_VERIFIER_BYTES)


def compute_code_challenge(verifier: str) -> str:
    """根据校验器计算 S256 PKCE code challenge。"""
    import hashlib

    return _base64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def _base64url_encode(data: bytes) -> str:
    """按 RFC 7636 与 OIDC 要求进行无填充 Base64url 编码。"""
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _cookie_name(provider: str) -> str:
    """根据提供者标识生成其专属 OIDC 状态 Cookie 名称。"""
    return f"{OIDC_STATE_COOKIE_PREFIX}{provider}"


def set_state_cookie(response: Response, request: Request, payload: OIDCStatePayload) -> None:
    """在响应中设置已签名的 OIDC 状态 Cookie。"""
    signed = _sign_state_payload(payload)
    is_https = is_secure_request(request)
    response.set_cookie(
        key=_cookie_name(payload.provider),
        value=signed,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=OIDC_STATE_MAX_AGE,
        path=f"/api/v1/auth/callback/{payload.provider}",
    )


def get_state_cookie(request: Request, provider: str) -> OIDCStatePayload | None:
    """读取并验证指定提供者的已签名 OIDC 状态 Cookie。"""
    signed = request.cookies.get(_cookie_name(provider))
    if not signed:
        return None
    return _verify_state_signed(signed)


def delete_state_cookie(response: Response, request: Request, provider: str) -> None:
    """删除 OIDC 状态 Cookie。"""
    is_https = is_secure_request(request)
    response.delete_cookie(
        key=_cookie_name(provider),
        secure=is_https,
        samesite="lax",
        path=f"/api/v1/auth/callback/{provider}",
    )
