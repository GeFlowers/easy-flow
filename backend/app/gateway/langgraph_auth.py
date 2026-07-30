"""LangGraph 兼容认证处理器，与 Gateway 共享 JWT 逻辑。

默认 DeerFlow 运行时嵌入 FastAPI Gateway；本模块保留给 LangGraph 工具、Studio
及 ``langgraph.json`` 的 ``auth.path`` 直连兼容路径。兼容路径复用 Gateway 的 JWT
和 CSRF 规则：``@auth.authenticate`` 验证会话及状态变更请求，``@auth.on`` 返回
元数据过滤条件，确保每个用户只能看到自己的线程。
"""

import secrets

from langgraph_sdk import Auth

from app.gateway.auth.errors import TokenError
from app.gateway.auth.jwt import decode_token
from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, is_auth_disabled
from app.gateway.deps import get_local_provider

auth = Auth()

# 按标准属于状态变更且必须进行跨站请求伪造验证的方法。
_CSRF_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def _check_csrf(request) -> None:
    """对状态变更请求强制双重提交 Cookie CSRF 校验。

    与 Gateway 的 ``CSRFMiddleware`` 保持一致，使经 nginx 直代理的 LangGraph
    路由获得相同 CSRF 防护。
    """
    method = getattr(request, "method", "") or ""
    if method.upper() not in _CSRF_METHODS:
        return

    if is_auth_disabled():
        return

    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("x-csrf-token")

    if not cookie_token or not header_token:
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail="CSRF token missing. Include X-CSRF-Token header.",
        )

    if not secrets.compare_digest(cookie_token, header_token):
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail="CSRF token mismatch.",
        )


@auth.authenticate
async def authenticate(request):
    """验证会话 Cookie、解码 JWT 并检查令牌版本。

    验证链与 Gateway 相同：Cookie、JWT 解码、数据库查询、令牌版本匹配；状态变更
    方法还会执行 CSRF 校验。
    """
    # 先做跨站请求伪造校验，使伪造请求即使携带有效会话凭据也能尽早被拒绝。
    _check_csrf(request)

    if is_auth_disabled():
        return AUTH_DISABLED_USER_ID

    token = request.cookies.get("access_token")
    if not token:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    payload = decode_token(token)
    if isinstance(payload, TokenError):
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Invalid token",
        )

    user = await get_local_provider().get_user(payload.sub)
    if user is None:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="User not found",
        )
    if user.token_version != payload.ver:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Token revoked (password changed)",
        )

    return payload.sub


@auth.on
async def add_owner_filter(ctx: Auth.types.AuthContext, value: dict):
    """写入时注入 ``user_id`` 元数据，读取时按该值过滤。

    Gateway 将线程所有权存为 ``metadata.user_id``；此处理器确保 LangGraph Server
    执行同等用户隔离。
    """
    # 创建或更新时在元数据写入用户标识。
    metadata = value.setdefault("metadata", {})
    metadata["user_id"] = ctx.user.identity

    # 返回过滤字典，运行时会将其用于搜索、读取和删除。
    return {"user_id": ctx.user.identity}
