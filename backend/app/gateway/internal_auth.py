"""供受信任 Gateway 内部调用方使用的认证。"""

from __future__ import annotations

import os
import secrets
from types import SimpleNamespace
from typing import Any

from deerflow.config.paths import make_safe_user_id
from deerflow.runtime.user_context import DEFAULT_USER_ID

INTERNAL_AUTH_HEADER_NAME = "X-DeerFlow-Internal-Token"
INTERNAL_OWNER_USER_ID_HEADER_NAME = "X-DeerFlow-Owner-User-Id"
INTERNAL_AUTH_ENV_VAR = "DEER_FLOW_INTERNAL_AUTH_TOKEN"
INTERNAL_SYSTEM_ROLE = "internal"


def _load_internal_auth_token() -> str:
    """读取内部认证令牌；未配置时生成当前工作进程专用令牌。"""
    token = os.environ.get(INTERNAL_AUTH_ENV_VAR)
    if token:
        return token
    return secrets.token_urlsafe(32)


_INTERNAL_AUTH_TOKEN = _load_internal_auth_token()


def create_internal_auth_headers(*, owner_user_id: str | None = None) -> dict[str, str]:
    """返回认证受信任 Gateway 内部调用所需的请求头。"""
    headers = {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}
    if owner_user_id:
        headers[INTERNAL_OWNER_USER_ID_HEADER_NAME] = owner_user_id
    return headers


def is_valid_internal_auth_token(token: str | None) -> bool:
    """当令牌与本 Gateway 工作进程的内部令牌匹配时返回 ``True``。"""
    return bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


def get_internal_user(owner_user_id: str | None = None):
    """返回供受信任内部频道调用使用的合成用户。

    提供 ``owner_user_id`` 时，合成用户携带实际频道所有者而非默认用户，确保 IM
    消息的每用户技能、记忆和线程数据使用正确隔离目录。所有者 ID 经
    :func:`make_safe_user_id` 规范化，防止特殊字符、路径片段或伪造头部逃逸存储桶
    或冒充其他用户；该规范化虽为有损映射，但不同原始输入不会共享安全 ID。
    """
    if owner_user_id:
        effective_id = make_safe_user_id(owner_user_id)
    else:
        effective_id = DEFAULT_USER_ID
    return SimpleNamespace(id=effective_id, system_role=INTERNAL_SYSTEM_ROLE)


def get_trusted_internal_owner_user_id(request: Any) -> str | None:
    """返回受信任内部请求中的所有者覆盖值；普通浏览器/API 请求忽略该头部。

    仅当 ``AuthMiddleware`` 已验证内部令牌并将合成内部用户写入请求状态后，才会
    信任该覆盖值。
    """
    user = getattr(getattr(request, "state", None), "user", None)
    if getattr(user, "system_role", None) != INTERNAL_SYSTEM_ROLE:
        return None

    owner_user_id = request.headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME)
    if not owner_user_id:
        return None
    owner_user_id = owner_user_id.strip()
    return owner_user_id or None
