"""FastAPI 的双重提交 Cookie CSRF 防护中间件。"""

import os
import secrets
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.gateway.auth.config import get_auth_config
from app.gateway.auth_disabled import is_auth_disabled

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_LENGTH = 64  # bytes


def is_secure_request(request: Request) -> bool:
    """根据受信任代理头判断客户端原始请求是否使用 HTTPS。"""
    return _request_scheme(request) == "https"


def generate_csrf_token() -> str:
    """生成密码学安全的随机 CSRF 令牌。"""
    return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)


def should_check_csrf(request: Request) -> bool:
    """判断请求是否需要 CSRF 校验，仅校验可能改变服务端持久化状态的方法。"""
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return False

    if is_auth_disabled():
        return False

    path = request.url.path.rstrip("/")
    # 查询当前身份不改变服务端状态，因此免除校验。
    if path == "/api/v1/auth/me":
        return False
    # 入站 Webhook 由供应方签名认证，不依赖浏览器双重提交 Cookie。
    if request.url.path.startswith("/api/webhooks/"):
        return False
    return True


_AUTH_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/login/local",
        "/api/v1/auth/logout",
        "/api/v1/auth/register",
        "/api/v1/auth/initialize",
    }
)


def is_auth_endpoint(request: Request) -> bool:
    """判断是否为首次建立会话时尚无 CSRF 令牌的身份接口。"""
    return request.url.path.rstrip("/") in _AUTH_EXEMPT_PATHS


def _host_with_optional_port(hostname: str, port: int | None, scheme: str) -> str:
    """返回规范化的主机及可选端口，并省略协议默认端口。"""
    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return host
    return f"{host}:{port}"


def _normalize_origin(origin: str) -> str | None:
    """将来源规范化为协议、主机和可选端口；非法输入返回空值。"""
    try:
        parsed = urlsplit(origin.strip())
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return None

    # 浏览器来源仅包含协议、主机和端口，拒绝路径或凭据等 URL 组成部分。
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        return None

    return f"{scheme}://{_host_with_optional_port(parsed.hostname, port, scheme)}"


def _configured_cors_origins() -> set[str]:
    """返回配置中允许调用身份接口的显式浏览器来源。"""
    origins = set()
    for raw_origin in os.environ.get("GATEWAY_CORS_ORIGINS", "").split(","):
        origin = raw_origin.strip()
        if not origin or origin == "*":
            continue
        normalized = _normalize_origin(origin)
        if normalized:
            origins.add(normalized)
    return origins


def get_configured_cors_origins() -> set[str]:
    """返回由环境变量配置并完成规范化的浏览器来源集合。"""
    return _configured_cors_origins()


def _first_header_value(value: str | None) -> str | None:
    """从逗号分隔的代理头中取出第一个值。"""
    if not value:
        return None
    first = value.split(",", 1)[0].strip()
    return first or None


def _forwarded_param(request: Request, name: str) -> str | None:
    """从第一个 Forwarded 代理头条目提取指定参数。"""
    forwarded = _first_header_value(request.headers.get("forwarded"))
    if not forwarded:
        return None

    for part in forwarded.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.lower() == name:
            return value.strip().strip('"') or None
    return None


def _request_scheme(request: Request) -> str:
    """从可信代理头解析客户端原始请求协议。"""
    scheme = _forwarded_param(request, "proto") or _first_header_value(request.headers.get("x-forwarded-proto")) or request.url.scheme
    return scheme.lower()


def _request_origin(request: Request) -> str | None:
    """构造浏览器当前访问目标的规范化来源。"""
    scheme = _request_scheme(request)
    host = _forwarded_param(request, "host") or _first_header_value(request.headers.get("x-forwarded-host")) or request.headers.get("host") or request.url.netloc

    forwarded_port = _first_header_value(request.headers.get("x-forwarded-port"))
    if forwarded_port and ":" not in host.rsplit("]", 1)[-1]:
        host = f"{host}:{forwarded_port}"

    return _normalize_origin(f"{scheme}://{host}")


def is_allowed_auth_origin(request: Request) -> bool:
    """仅允许同源或显式配置来源发起会话建立请求。

    首次登录等请求没有令牌却会写入会话 Cookie，必须通过来源限制防止登录 CSRF；
    缺少来源头的非浏览器客户端仍可访问。
    """
    origin = request.headers.get("origin")
    if not origin:
        return True

    normalized_origin = _normalize_origin(origin)
    if normalized_origin is None:
        return False

    request_origin = _request_origin(request)
    return normalized_origin in _configured_cors_origins() or (request_origin is not None and normalized_origin == request_origin)


class CSRFMiddleware(BaseHTTPMiddleware):
    """以双重提交 Cookie 模式保护会改变状态的浏览器请求。"""

    def __init__(self, app: ASGIApp) -> None:
        """初始化中间件并保留 Starlette 下游应用。"""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """校验请求令牌及来源，并在建立会话后下发与会话同寿命的令牌。"""
        _is_auth = is_auth_endpoint(request)

        if should_check_csrf(request) and _is_auth and not is_allowed_auth_origin(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-site auth request denied."},
            )

        if should_check_csrf(request) and not _is_auth:
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
            header_token = request.headers.get(CSRF_HEADER_NAME)

            if not cookie_token or not header_token:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing. Include X-CSRF-Token header."},
                )

            if not secrets.compare_digest(cookie_token, header_token):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch."},
                )

        response = await call_next(request)

        # 会话建立接口还需下发与会话配对的 CSRF Cookie。
        if _is_auth and request.method == "POST":
            # 为新会话生成独立令牌，避免复用旧浏览器状态。
            csrf_token = generate_csrf_token()
            is_https = is_secure_request(request)
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=csrf_token,
                httponly=False,  # 双重提交模式要求前端脚本可读取并回传该 Cookie。
                secure=is_https,
                samesite="strict",
                # 与会话 Cookie 同寿命，避免持久会话尚存而会话级 CSRF Cookie 被浏览器清除。
                max_age=get_auth_config().token_expiry_days * 24 * 3600 if is_https else None,
            )

        return response


def get_csrf_token(request: Request) -> str | None:
    """从当前请求 Cookie 读取 CSRF 令牌，供服务端渲染嵌入表单或请求头。"""
    return request.cookies.get(CSRF_COOKIE_NAME)
