"""全局认证中间件，以失败关闭方式作为安全兜底。

该中间件为非公开路径拒绝未认证请求，并将已验证 JWT 对应的 ``User`` 写入
``request.state.user`` 与用户上下文，以自动执行仓储层所有者过滤；细粒度权限
控制仍由 ``authz.py`` 的装饰器完成。
"""

from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.auth_disabled import (
    AUTH_SOURCE_AUTH_DISABLED,
    AUTH_SOURCE_INTERNAL,
    AUTH_SOURCE_SESSION,
    get_auth_disabled_user,
    is_auth_disabled,
)
from app.gateway.authz import _ALL_PERMISSIONS, AuthContext
from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, get_internal_user, is_valid_internal_auth_token
from deerflow.runtime.user_context import reset_current_user, set_current_user

# 永远不要求认证的路径。
_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/oauth/",
    "/api/v1/auth/callback/",
    # 入站回调通过提供者专属签名认证，而非会话凭据。
    "/api/webhooks/",
)

# 精确匹配的公开认证路径（登录、注册和状态检查）。
# 查询当前用户、修改密码等路径不公开。
_PUBLIC_EXACT_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/login/local",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
        "/api/v1/auth/initialize",
        "/api/v1/auth/providers",
    }
)


def _is_public(path: str) -> bool:
    """判断请求路径是否属于无需认证的公开路径。"""
    stripped = path.rstrip("/")
    if stripped in _PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """严格认证关卡，拒绝没有有效会话的请求。

    对非公开路径先检查 Cookie 是否存在，再严格验证 JWT；成功后写入请求状态和
    用户上下文，使仓储层所有者过滤自动生效。资源级授权仍应使用
    ``@require_permission(..., owner_check=True)`` 显式检查。
    """

    def __init__(self, app: ASGIApp) -> None:
        """使用 ASGI 应用初始化认证中间件。"""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """认证请求、建立用户上下文，并将请求交给后续中间件或处理器。"""
        if _is_public(request.url.path):
            return await call_next(request)

        internal_user = None
        if is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
            # 从可信头部提取频道所有者标识。存在时，合成内部用户携带实际所有者
            # 身份，使有效用户标识及每用户文件路径（自定义技能、记忆、线程数据）
            # 解析为即时通信频道用户而非回退到默认用户。
            from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

            owner_user_id = request.headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME)
            if owner_user_id:
                owner_user_id = owner_user_id.strip()
            internal_user = get_internal_user(owner_user_id=owner_user_id or None)

        auth_source = AUTH_SOURCE_SESSION
        access_token = request.cookies.get("access_token")

        # 非公开路径必须有会话凭据，或使用已验证的内部认证。
        if internal_user is not None:
            user = internal_user
            auth_source = AUTH_SOURCE_INTERNAL
        elif access_token:
            # 严格验证令牌：立即以 401 拒绝无效或过期令牌，避免任意形似会话凭据的
            # 字符串绕过认证并访问非隔离路由。调用严格解析器可保留细分错误码；
            # 当前中间件基类不能让异常向外冒泡，故在此渲染结构化响应。
            from app.gateway.deps import get_current_user_from_request

            try:
                user = await get_current_user_from_request(request)
            except HTTPException as exc:
                if not is_auth_disabled():
                    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
                user = get_auth_disabled_user()
                auth_source = AUTH_SOURCE_AUTH_DISABLED
        elif is_auth_disabled():
            user = get_auth_disabled_user()
            auth_source = AUTH_SOURCE_AUTH_DISABLED
        else:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": AuthErrorResponse(
                        code=AuthErrorCode.NOT_AUTHENTICATED,
                        message="Authentication required",
                    ).model_dump()
                },
            )

        # 同时写入用户状态和认证状态，使权限检查不会在同一请求中再次执行令牌解码和数据库查询。
        request.state.user = user
        request.state.auth_source = auth_source
        request.state.auth = AuthContext(user=user, permissions=_ALL_PERMISSIONS)
        token = set_current_user(user)
        try:
            return await call_next(request)
        finally:
            reset_current_user(token)
