"""认证提供者抽象接口。"""

from abc import ABC, abstractmethod


class AuthProvider(ABC):
    """所有认证提供者实现的抽象基类。"""

    @abstractmethod
    async def authenticate(self, credentials: dict) -> "User | None":
        """使用给定凭据认证用户，失败时返回 ``None``。"""
        raise NotImplementedError

    @abstractmethod
    async def get_user(self, user_id: str) -> "User | None":
        """按 ID 获取用户。"""
        raise NotImplementedError


# 在运行时导入用户模型，以避免循环导入。
from app.gateway.auth.models import User  # noqa: E402
