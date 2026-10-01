'''身份验证端点。'''

import asyncio
import logging
import os
import re
import secrets
import time
import urllib.parse
from ipaddress import ip_address, ip_network

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, field_validator
from starlette.responses import RedirectResponse

from app.gateway.auth import (
    UserResponse,
    create_access_token,
)
from app.gateway.auth.config import get_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.auth.oidc import OIDCError, OIDCService
from app.gateway.auth.oidc_state import (
    OIDCStatePayload,
    compute_code_challenge,
    delete_state_cookie,
    generate_code_verifier,
    generate_nonce,
    generate_oidc_state,
    get_state_cookie,
    set_state_cookie,
)
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, _request_origin, generate_csrf_token, is_secure_request
from app.gateway.deps import get_current_user_from_request, get_local_provider
from deerflow.config.auth_config import OIDCProviderConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ── 请求与响应模型 ───────────────────────────────────────────────────────


class LoginResponse(BaseModel):
    '''登录的响应模型 — 令牌仅存在于 HttpOnly cookie 中。'''

    expires_in: int  # 有效期（秒）
    needs_setup: bool = False


# 常见弱密码黑名单：取自公开 SecLists 的“10k worst passwords”集合，仅保留小写且长度
# 不少于 8 的条目（更短的密码已被 `min_length` 拦截）。该清单刻意保持精简，仅提供
# 基础防线，不替代完整的 HIBP / passlib 校验；每次请求在进程内执行。
_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty12",
        "qwertyui",
        "qwerty123",
        "abc12345",
        "abcd1234",
        "iloveyou",
        "letmein1",
        "welcome1",
        "welcome123",
        "admin123",
        "administrator",
        "passw0rd",
        "p@ssw0rd",
        "monkey12",
        "trustno1",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "superman",
        "batman123",
        "starwars",
        "dragon123",
        "master123",
        "shadow12",
        "michael1",
        "jennifer",
        "computer",
    }
)


def _password_is_common(password: str) -> bool:
    '''不区分大小写地检查密码是否在常见弱密码黑名单中。

    将输入转为小写，使 ``Password`` 和 ``PASSWORD`` 等简单变体也会被拒绝。
    不对数字替换进行归一化；``p@ssw0rd`` 以字面量方式包含在黑名单中，以保持规则
    低成本且可预测。
    '''
    return password.lower() in _COMMON_PASSWORDS


def _validate_strong_password(value: str) -> str:
    '''供 `RegisterRequest` 与 `ChangePasswordRequest` 共用的 Pydantic 字段验证器。

    密码强度约束提取为函数而非类型级 mixin：两个请求模型不存在继承关系，只共享
    校验规则。各模型通过 ``@field_validator(field_name)`` 绑定该函数，无需引入继承。
    '''
    if _password_is_common(value):
        raise ValueError("Password is too common; choose a stronger password.")
    return value


class RegisterRequest(BaseModel):
    '''用户注册请求模型。'''

    email: EmailStr
    password: str = Field(..., min_length=8)

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class ChangePasswordRequest(BaseModel):
    '''密码更改的请求模型（还处理设置流程）。'''

    current_password: str
    new_password: str = Field(..., min_length=8)
    new_email: EmailStr | None = None

    _strong_password = field_validator("new_password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class MessageResponse(BaseModel):
    '''通用消息响应。'''

    message: str


# ── 辅助函数 ─────────────────────────────────────────────────────────────


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    '''在响应上设置 access_token HttpOnly cookie。'''
    config = get_auth_config()
    is_https = is_secure_request(request)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=config.token_expiry_days * 24 * 3600 if is_https else None,
    )


# ── 限流 ─────────────────────────────────────────────────────────────────
# 进程内字典，不在多个 worker 间共享。
# **限制**：多 worker 部署（如 `gunicorn -w N`）中，每个 worker 维护各自的锁定表，
# 攻击者在所有 worker 被锁定前实际上可尝试 `N × _MAX_LOGIN_ATTEMPTS` 次。生产环境
# 的多 worker 部署应替换为共享存储（Redis 或数据库计数器），才能严格执行每 IP 限制。

_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 分钟

# IP → （失败次数，锁定截止时间戳）
_login_attempts: dict[str, tuple[int, float]] = {}


def _trusted_proxies() -> list:
    '''将环境变量 `AUTH_TRUSTED_PROXIES` 解析为 `ip_network` 对象列表。

    该变量接受以逗号分隔的 CIDR 或单个 IP。空值或未设置表示不信任任何代理
    （直连模式）。无效条目会被跳过并记录警告。每次实时读取，以便环境变量覆盖
    立即生效，测试也可通过 ``monkeypatch.setenv`` 生效而无需修改模块级缓存。
    '''
    raw = os.getenv("AUTH_TRUSTED_PROXIES", "").strip()
    if not raw:
        return []
    nets = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            nets.append(ip_network(entry, strict=False))
        except ValueError:
            logger.warning("AUTH_TRUSTED_PROXIES: ignoring invalid entry %r", entry)
    return nets


def _get_client_ip(request: Request) -> str:
    '''提取用于限流的真实客户端 IP。

    信任模型：

    - TCP 对端（``request.client.host``）始终是基准值。它由内核从连接套接字获取，
      客户端自身无法伪造。
    - 仅当 TCP 对端位于 `AUTH_TRUSTED_PROXIES` 白名单时，才信任 `X-Real-IP`。该
      白名单通过环境变量设置，可包含逗号分隔的 CIDR 或单个 IP；配置后，假定网关位于
      会将 `X-Real-IP` 覆盖为原始客户端地址的反向代理（nginx、Cloudflare、ALB 等）之后。
    - 未设置 `AUTH_TRUSTED_PROXIES` 时，静默忽略 `X-Real-IP`，避免客户端在开发或
      直连网关模式中轮换该请求头以绕过每 IP 限流。

    有意不使用 `X-Forwarded-For`：其首跳天然可由客户端控制，且信任链难以按请求审计。
    '''
    peer_host = request.client.host if request.client else None

    trusted = _trusted_proxies()
    if trusted and peer_host:
        try:
            peer_ip = ip_address(peer_host)
            if any(peer_ip in net for net in trusted):
                real_ip = request.headers.get("x-real-ip", "").strip()
                if real_ip:
                    return real_ip
        except ValueError:
            # `peer_host` 不是可解析的 IP（如 `"unknown"`），继续使用回退值。
            pass

    return peer_host or "unknown"


def _check_rate_limit(ip: str) -> None:
    '''如果 IP 当前被锁定，则引发 429。'''
    record = _login_attempts.get(ip)
    if record is None:
        return
    fail_count, lock_until = record
    if fail_count >= _MAX_LOGIN_ATTEMPTS:
        if time.time() < lock_until:
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
            )
        del _login_attempts[ip]


_MAX_TRACKED_IPS = 10000


def _record_login_failure(ip: str) -> None:
    '''记录给定 IP 的失败登录尝试。'''
    # 字典过大时清理已过期的锁定记录。
    if len(_login_attempts) >= _MAX_TRACKED_IPS:
        now = time.time()
        expired = [k for k, (c, t) in _login_attempts.items() if c >= _MAX_LOGIN_ATTEMPTS and now >= t]
        for k in expired:
            del _login_attempts[k]
        # 若仍超限，则淘汰损失最小的一半：未达到阈值的 IP（`lock_until=0.0`）排在最前，
        # 其次是最早过期的锁定记录。
        if len(_login_attempts) >= _MAX_TRACKED_IPS:
            by_time = sorted(_login_attempts.items(), key=lambda kv: kv[1][1])
            for k, _ in by_time[: len(by_time) // 2]:
                del _login_attempts[k]

    record = _login_attempts.get(ip)
    if record is None:
        _login_attempts[ip] = (1, 0.0)
    else:
        new_count = record[0] + 1
        lock_until = time.time() + _LOCKOUT_SECONDS if new_count >= _MAX_LOGIN_ATTEMPTS else 0.0
        _login_attempts[ip] = (new_count, lock_until)


def _record_login_success(ip: str) -> None:
    '''成功登录后清除给定 IP 的失败计数器。'''
    _login_attempts.pop(ip, None)


# ── 端点 ─────────────────────────────────────────────────────────────────


@router.post("/login/local", response_model=LoginResponse)
async def login_local(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    '''本地电子邮件/密码登录。'''
    client_ip = _get_client_ip(request)
    _check_rate_limit(client_ip)

    user = await get_local_provider().authenticate({"email": form_data.username, "password": form_data.password})

    if user is None:
        _record_login_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="Incorrect email or password").model_dump(),
        )

    _record_login_success(client_ip)
    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return LoginResponse(
        expires_in=get_auth_config().token_expiry_days * 24 * 3600,
        needs_setup=user.needs_setup,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, response: Response, body: RegisterRequest):
    '''注册新的用户账户（固定授予 `user` 角色）。

    首个管理员须通过 `/initialize` 显式创建；本端点仅创建普通用户，并通过设置会话
    cookie 自动登录。
    '''
    try:
        user = await get_local_provider().create_user(email=body.email, password=body.password, system_role="user")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already registered").model_dump(),
        )

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role, oauth_provider=user.oauth_provider)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response):
    '''通过清除 cookie 注销当前用户。'''
    response.delete_cookie(key="access_token", secure=is_secure_request(request), samesite="lax")
    return MessageResponse(message="Successfully logged out")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(request: Request, response: Response, body: ChangePasswordRequest):
    '''修改当前已认证用户的密码，并处理首次启动设置。

    - 提供 `new_email` 时更新邮箱并校验唯一性；
    - 当 `user.needs_setup` 为 `True` 且提供 `new_email` 时，清除 `needs_setup`；
    - 始终递增 `token_version`，使旧会话失效；
    - 使用新的 `token_version` 重新签发会话 cookie。
    '''
    from app.gateway.auth.password import hash_password_async, verify_password_async
    from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED

    user = await get_current_user_from_request(request)

    if getattr(request.state, "auth_source", None) == AUTH_SOURCE_AUTH_DISABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="Password changes are not available when DEER_FLOW_AUTH_DISABLED=1.",
            ).model_dump(),
        )

    if user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="OAuth users cannot change password").model_dump())

    if not await verify_password_async(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="Current password is incorrect").model_dump())

    provider = get_local_provider()

    # 如提供新邮箱则更新。
    if body.new_email is not None:
        existing = await provider.get_user_by_email(body.new_email)
        if existing and str(existing.id) != str(user.id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already in use").model_dump())
        user.email = body.new_email

    # 更新密码并递增令牌版本。
    user.password_hash = await hash_password_async(body.new_password)
    user.token_version += 1

    # 首次设置流程完成后清除设置标记。
    if user.needs_setup and body.new_email is not None:
        user.needs_setup = False

    await provider.update_user(user)

    # 使用新的 `token_version` 重新签发 cookie。
    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return MessageResponse(message="Password changed successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request):
    '''获取当前经过身份验证的用户信息。'''
    user = await get_current_user_from_request(request)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        system_role=user.system_role,
        needs_setup=user.needs_setup,
        oauth_provider=user.oauth_provider,
    )


# 每 IP 缓存：IP → （时间戳，结果字典）。
# 在 TTL 内直接返回缓存而非 429：管理员是否存在通常不会频繁变化，而 429 会打断多
# 标签页或服务重启后的集中重连。
_SETUP_STATUS_CACHE: dict[str, tuple[float, dict]] = {}
_SETUP_STATUS_CACHE_TTL_SECONDS = 60
_MAX_TRACKED_SETUP_STATUS_IPS = 10000
_SETUP_STATUS_INFLIGHT: dict[str, asyncio.Task[dict]] = {}
_SETUP_STATUS_INFLIGHT_GUARD = asyncio.Lock()


@router.get("/setup-status")
async def setup_status(request: Request):
    '''检查是否存在管理员账户；不存在时返回 `needs_setup=True`。'''
    client_ip = _get_client_ip(request)
    now = time.time()

    # TTL 内返回缓存，避免多标签页重连触发 429。
    cached = _SETUP_STATUS_CACHE.get(client_ip)
    if cached is not None:
        cached_time, cached_result = cached
        if now - cached_time < _SETUP_STATUS_CACHE_TTL_SECONDS:
            return cached_result

    async with _SETUP_STATUS_INFLIGHT_GUARD:
        # 等待进行中的任务保护锁后再次检查缓存。
        now = time.time()
        cached = _SETUP_STATUS_CACHE.get(client_ip)
        if cached is not None:
            cached_time, cached_result = cached
            if now - cached_time < _SETUP_STATUS_CACHE_TTL_SECONDS:
                return cached_result

        task = _SETUP_STATUS_INFLIGHT.get(client_ip)
        if task is None:
            # 字典过大时清理过期条目，以限制内存使用。
            if len(_SETUP_STATUS_CACHE) >= _MAX_TRACKED_SETUP_STATUS_IPS:
                cutoff = now - _SETUP_STATUS_CACHE_TTL_SECONDS
                stale = [k for k, (t, _) in _SETUP_STATUS_CACHE.items() if t < cutoff]
                for k in stale:
                    del _SETUP_STATUS_CACHE[k]
                if len(_SETUP_STATUS_CACHE) >= _MAX_TRACKED_SETUP_STATUS_IPS:
                    by_time = sorted(_SETUP_STATUS_CACHE.items(), key=lambda entry: entry[1][0])
                    for k, _ in by_time[: len(by_time) // 2]:
                        del _SETUP_STATUS_CACHE[k]

            async def _compute_setup_status() -> dict:
                '''查询管理员数量并生成首次设置状态。'''
                admin_count = await get_local_provider().count_admin_users()
                return {"needs_setup": admin_count == 0}

            task = asyncio.create_task(_compute_setup_status())
            _SETUP_STATUS_INFLIGHT[client_ip] = task

    try:
        result = await task
    finally:
        async with _SETUP_STATUS_INFLIGHT_GUARD:
            if _SETUP_STATUS_INFLIGHT.get(client_ip) is task:
                del _SETUP_STATUS_INFLIGHT[client_ip]

    # 仅缓存稳定的“已初始化”结果，避免首次设置重定向过期。
    if result["needs_setup"] is False:
        _SETUP_STATUS_CACHE[client_ip] = (time.time(), result)
    else:
        _SETUP_STATUS_CACHE.pop(client_ip, None)
    return result


class InitializeAdminRequest(BaseModel):
    '''请求创建首次启动管理员帐户的模型。'''

    email: EmailStr
    password: str = Field(..., min_length=8)

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v)))


@router.post("/initialize", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def initialize_admin(request: Request, response: Response, body: InitializeAdminRequest):
    '''在系统首次设置期间创建首个管理员账户。

    仅在不存在管理员时可调用；若管理员已存在则返回 409 Conflict。成功后以
    `needs_setup=False` 创建管理员账户，并设置会话 cookie。
    '''
    admin_count = await get_local_provider().count_admin_users()
    if admin_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthErrorResponse(code=AuthErrorCode.SYSTEM_ALREADY_INITIALIZED, message="System already initialized").model_dump(),
        )

    try:
        user = await get_local_provider().create_user(email=body.email, password=body.password, system_role="admin", needs_setup=False)
    except ValueError:
        admin_count = await get_local_provider().count_admin_users()
        if admin_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already registered").model_dump(),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthErrorResponse(code=AuthErrorCode.SYSTEM_ALREADY_INITIALIZED, message="System already initialized").model_dump(),
        )

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role, oauth_provider=user.oauth_provider)


# ── OIDC / SSO 端点 ──────────────────────────────────────────────────────

_OIDC_PROVIDER_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _get_oidc_service() -> OIDCService:
    '''获取（或创建）单例 OIDC 服务实例。'''
    if not hasattr(_get_oidc_service, "_instance"):
        _get_oidc_service._instance = OIDCService()  # type: ignore[attr-defined]
    return _get_oidc_service._instance  # type: ignore[attr-defined]


async def close_oidc_service() -> None:
    '''关闭已创建的 OIDC 服务实例并清除单例缓存。'''
    service = getattr(_get_oidc_service, "_instance", None)
    if service is not None:
        await service.close()
        delattr(_get_oidc_service, "_instance")


def _set_csrf_cookie(response: Response, request: Request) -> None:
    '''设置 CSRF 双重提交 cookie（基于 GET 的 OIDC 回调需要）。'''
    csrf_token = generate_csrf_token()
    is_https = is_secure_request(request)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,  # 双重提交 Cookie 模式要求 JavaScript 可读取该值。
        secure=is_https,
        samesite="strict",
        # 与 `access_token` 保持相同有效期（见 `_set_session_cookie`），使双重提交
        # Cookie 同时失效，避免仍登录的会话丢失 `csrf_token`（如 iOS Safari PWA 被终止）。
        max_age=get_auth_config().token_expiry_days * 24 * 3600 if is_https else None,
    )


def _resolve_oidc_redirect_uri(request: Request, provider_id: str, provider_config: OIDCProviderConfig) -> str:
    '''解析 OIDC 提供商的回调 URI。

    优先使用显式配置的 `redirect_uri`；未配置时，基于请求自身的基础 URL 构造开发环境回调地址。
    '''
    if provider_config.redirect_uri:
        return provider_config.redirect_uri

    # 开发环境回退时，使用具备代理感知能力的请求来源（与 CSRF 来源校验一致地处理
    # `Forwarded` / `X-Forwarded-*`），而非原始 `Host` 请求头。这样可防止伪造的
    # `Host` 篡改 IdP 的 `redirect_uri`，并正确反映代理后的客户端协议。
    origin = _request_origin(request)
    if not origin:
        origin = f"{request.url.scheme}://{request.headers.get('host', 'localhost:8001')}"
    return f"{origin}/api/v1/auth/callback/{provider_id}"


@router.get("/providers")
async def list_auth_providers():
    '''列出登录页可用的 SSO 提供商。

    仅返回可安全暴露给前端的元数据，不包含密钥、端点或内部配置。
    '''
    from deerflow.config.app_config import get_app_config

    app_config = get_app_config()
    oidc_config = app_config.auth.oidc

    if not oidc_config.enabled:
        return {"providers": []}

    providers = []
    for provider_id, provider_cfg in oidc_config.providers.items():
        providers.append(
            {
                "id": provider_id,
                "display_name": provider_cfg.display_name,
                "type": "oidc",
            }
        )
    return {"providers": providers}


@router.get("/oauth/{provider}")
async def oauth_login(
    request: Request,
    provider: str,
    # 有意使用内置名称 `next`，以与查询参数名保持一致。
    next: str | None = None,  # noqa: A002
):
    '''发起 OIDC 登录流程。

    重定向至 OIDC 提供商的授权 URL，并携带 state、nonce 与 PKCE 参数。`next` 查询参数
    指定登录成功后的跳转位置，默认为 `/workspace`。
    '''
    from deerflow.config.app_config import get_app_config

    app_config = get_app_config()
    oidc_config = app_config.auth.oidc

    if not oidc_config.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO authentication is not enabled")

    if not _OIDC_PROVIDER_KEY_RE.match(provider):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid provider ID")

    provider_config = oidc_config.providers.get(provider)
    if not provider_config:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown SSO provider: {provider}")

    # 校验 `next`，防止开放重定向。
    redirect_path = validate_next_param(next) or "/workspace"

    # 解析回调 URI。
    redirect_uri = _resolve_oidc_redirect_uri(request, provider, provider_config)

    # 生成 state、nonce 与 PKCE 参数。
    state_value = generate_oidc_state()
    nonce_value = generate_nonce() if provider_config.nonce_enabled else None
    code_verifier = generate_code_verifier() if provider_config.pkce_enabled else None
    code_challenge = compute_code_challenge(code_verifier) if code_verifier else None

    # 通过发现端点获取提供商元数据。
    overrides = {
        "authorization_endpoint": provider_config.authorization_endpoint,
        "token_endpoint": provider_config.token_endpoint,
        "userinfo_endpoint": provider_config.userinfo_endpoint,
        "jwks_uri": provider_config.jwks_uri,
    }
    service = _get_oidc_service()
    try:
        metadata = await service.discover(provider_config.issuer, overrides)
    except OIDCError as exc:
        logger.error("OIDC discovery failed for provider %s: %s", provider, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to SSO provider")

    auth_url = service.build_authorization_url(
        metadata=metadata,
        client_id=provider_config.client_id,
        redirect_uri=redirect_uri,
        scopes=provider_config.scopes,
        state=state_value,
        nonce=nonce_value,
        code_challenge=code_challenge,
    )

    # 设置已签名的 state cookie。
    state_payload = OIDCStatePayload(
        provider=provider,
        state=state_value,
        nonce=nonce_value,
        code_verifier=code_verifier,
        next_path=redirect_path,
    )
    redirect_response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    set_state_cookie(redirect_response, request, state_payload)

    return redirect_response


@router.get("/callback/{provider}")
async def oauth_callback(
    request: Request,
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    '''处理 OIDC 授权后的回调。

    验证 state cookie，以授权码交换令牌并校验 ID Token，随后创建或关联 DeerFlow 用户，
    最后设置会话 cookie。
    '''
    from deerflow.config.app_config import get_app_config

    app_config = get_app_config()
    oidc_config = app_config.auth.oidc

    # ── 提供商错误 ──────────────────────────────────────────────────
    if error:
        logger.warning("OIDC provider returned error for %s: %s (description: %s)", provider, error, error_description)
        redirect = _build_error_redirect(oidc_config.frontend_base_url, "sso_failed")
        return RedirectResponse(url=redirect, status_code=status.HTTP_302_FOUND)

    if not oidc_config.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO authentication is not enabled")

    if not _OIDC_PROVIDER_KEY_RE.match(provider):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid provider ID")

    provider_config = oidc_config.providers.get(provider)
    if not provider_config:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown SSO provider: {provider}")

    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state parameter")

    # ── 校验 state cookie ────────────────────────────────────────────
    state_payload = get_state_cookie(request, provider)
    if not state_payload:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing or expired OIDC state cookie")

    if not secrets.compare_digest(state_payload.state, state):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OIDC state mismatch")

    # ── 解析回调 URI ─────────────────────────────────────────────────
    redirect_uri = _resolve_oidc_redirect_uri(request, provider, provider_config)

    # ── 获取元数据 ───────────────────────────────────────────────────
    overrides = {
        "authorization_endpoint": provider_config.authorization_endpoint,
        "token_endpoint": provider_config.token_endpoint,
        "userinfo_endpoint": provider_config.userinfo_endpoint,
        "jwks_uri": provider_config.jwks_uri,
    }
    service = _get_oidc_service()
    try:
        metadata = await service.discover(provider_config.issuer, overrides)
    except OIDCError as exc:
        logger.error("OIDC discovery failed for provider %s during callback: %s", provider, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to SSO provider")

    # ── 身份验证 ─────────────────────────────────────────────────────
    try:
        identity = await service.authenticate_callback(
            provider_id=provider,
            metadata=metadata,
            client_id=provider_config.client_id,
            client_secret=provider_config.client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=state_payload.code_verifier,
            nonce=state_payload.nonce,
            auth_method=provider_config.token_endpoint_auth_method,
        )
    except OIDCError as exc:
        logger.error("OIDC callback authentication failed for %s: %s", provider, exc)
        redirect = _build_error_redirect(oidc_config.frontend_base_url, "sso_failed")
        return RedirectResponse(url=redirect, status_code=status.HTTP_302_FOUND)

    # ── 创建或关联用户 ───────────────────────────────────────────────
    try:
        result = await get_or_provision_oidc_user(provider, provider_config, identity, get_local_provider())
    except HTTPException as exc:
        error_map = {
            status.HTTP_403_FORBIDDEN: "sso_not_allowed",
            status.HTTP_409_CONFLICT: "sso_account_exists",
        }
        error_code = error_map.get(exc.status_code, "sso_failed")
        logger.warning("OIDC user provisioning failed for %s (%s): %s", identity.email, provider, exc.detail)
        redirect = _build_error_redirect(oidc_config.frontend_base_url, error_code)
        return RedirectResponse(url=redirect, status_code=status.HTTP_302_FOUND)

    user = result["user"]

    # ── 签发 DeerFlow 会话 ───────────────────────────────────────────
    token = create_access_token(str(user.id), token_version=user.token_version)

    redirect_target = state_payload.next_path or "/workspace"
    frontend_base = oidc_config.frontend_base_url or ""
    callback_redirect = f"{frontend_base}/auth/callback?next={urllib.parse.quote(redirect_target)}"

    redirect_response = RedirectResponse(url=callback_redirect, status_code=status.HTTP_302_FOUND)

    # 设置会话 cookie（复用现有辅助函数）。
    _set_session_cookie(redirect_response, token, request)

    # 回调为 GET 请求，CSRF 中间件不会设置 cookie，故在此补充设置。
    _set_csrf_cookie(redirect_response, request)

    # 删除 state cookie。
    delete_state_cookie(redirect_response, request, provider)

    return redirect_response


def _build_error_redirect(frontend_base_url: str | None, error_code: str) -> str:
    '''构建带有错误参数的前端重定向 URL。'''
    base = frontend_base_url or ""
    return f"{base}/login?error={error_code}"


def validate_next_param(next_param: str | None) -> str | None:
    '''校验并清理 `next` 重定向参数。

    仅允许以 `/` 开头的相对路径；拒绝协议相对 URL（`//`）、绝对 URL 以及内嵌协议的 URL。
    '''
    if not next_param:
        return None
    if not next_param.startswith("/"):
        return None
    if next_param.startswith("//") or next_param.startswith("http://") or next_param.startswith("https://"):
        return None
    if ":" in next_param:
        return None
    return next_param
