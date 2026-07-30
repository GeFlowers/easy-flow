"""DeerFlow 的认证模块。

本模块提供基于 JWT 的认证、可扩展认证提供者以及用户存储仓储接口。
"""

from app.gateway.auth.config import AuthConfig, get_auth_config, set_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError
from app.gateway.auth.jwt import TokenPayload, create_access_token, decode_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User, UserResponse
from app.gateway.auth.password import hash_password, verify_password
from app.gateway.auth.providers import AuthProvider
from app.gateway.auth.repositories.base import UserRepository

__all__ = [
    # 配置
    "AuthConfig",
    "get_auth_config",
    "set_auth_config",
    # 错误类型
    "AuthErrorCode",
    "AuthErrorResponse",
    "TokenError",
    # 令牌处理
    "TokenPayload",
    "create_access_token",
    "decode_token",
    # 密码处理
    "hash_password",
    "verify_password",
    # 数据模型
    "User",
    "UserResponse",
    # 认证提供者
    "AuthProvider",
    "LocalAuthProvider",
    # 仓储接口
    "UserRepository",
]
