'''身份验证端点。'''

import logging
import os
import time
from ipaddress import ip_address, ip_network

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, field_validator

from server.gateway.auth import (
    UserResponse,
    create_access_token,
)
from server.gateway.auth.config import get_auth_config
from server.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from server.gateway.csrf_middleware import is_secure_request
from server.gateway.deps import get_current_user_from_request, get_local_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ── 请求与响应模型 ───────────────────────────────────────────────────────


class LoginResponse(BaseModel):
    '''登录的响应模型 — 令牌仅存在于 HttpOnly cookie 中。'''

    expires_in: int  # 有效期（秒）


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


def _validate_strong_password(value: str) -> str:
    '''供 `RegisterRequest` 与 `ChangePasswordRequest` 共用的 Pydantic 字段验证器。

    密码强度约束提取为函数而非类型级 mixin：两个请求模型不存在继承关系，只共享
    校验规则。各模型通过 ``@field_validator(field_name)`` 绑定该函数，无需引入继承。
    '''
    if _password_is_common(value):
        raise ValueError("Password is too common; choose a stronger password.")
    return value


def _password_is_common(password: str) -> bool:
    '''不区分大小写地检查密码是否在常见弱密码黑名单中。

    将输入转为小写，使 ``Password`` 和 ``PASSWORD`` 等简单变体也会被拒绝。
    不对数字替换进行归一化；``p@ssw0rd`` 以字面量方式包含在黑名单中，以保持规则
    低成本且可预测。
    '''
    return password.lower() in _COMMON_PASSWORDS


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
    )


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


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, response: Response, body: RegisterRequest):
    '''注册用户并设置会话 Cookie。'''
    try:
        user = await get_local_provider().create_user(email=body.email, password=body.password)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already registered").model_dump(),
        )

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return UserResponse(id=str(user.id), email=user.email)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response):
    '''通过清除 cookie 注销当前用户。'''
    response.delete_cookie(key="access_token", secure=is_secure_request(request), samesite="lax")
    return MessageResponse(message="Successfully logged out")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(request: Request, response: Response, body: ChangePasswordRequest):
    '''修改当前已认证用户的密码。

    - 提供 `new_email` 时更新邮箱并校验唯一性；
    - 始终递增 `token_version`，使旧会话失效；
    - 使用新的 `token_version` 重新签发会话 cookie。
    '''
    from server.gateway.auth.password import hash_password_async, verify_password_async
    from server.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="Account has no local password").model_dump())

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

    await provider.update_user(user)

    # 使用新的 `token_version` 重新签发 cookie。
    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return MessageResponse(message="Password changed successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request):
    '''获取当前经过身份验证的用户信息。'''
    user = await get_current_user_from_request(request)
    return UserResponse(id=str(user.id), email=user.email)
