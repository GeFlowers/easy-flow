"""本地邮箱与密码认证提供者。"""

import logging

from app.gateway.auth.models import User
from app.gateway.auth.password import hash_password_async, needs_rehash, verify_password_async
from app.gateway.auth.providers import AuthProvider
from app.gateway.auth.repositories.base import UserRepository

logger = logging.getLogger(__name__)


class LocalAuthProvider(AuthProvider):
    """使用本地数据库验证邮箱和密码的认证提供者。"""

    def __init__(self, repository: UserRepository):
        """使用指定的 ``UserRepository`` 初始化认证提供者。"""
        self._repo = repository

    async def authenticate(self, credentials: dict) -> User | None:
        """使用凭据中的邮箱和密码认证，失败时返回 ``None``。"""
        email = credentials.get("email")
        password = credentials.get("password")

        if not email or not password:
            return None

        user = await self._repo.get_user_by_email(email)
        if user is None:
            return None

        if user.password_hash is None:
            # 第三方登录用户没有本地密码，不能通过本地密码流程登录。
            return None

        if not await verify_password_async(password, user.password_hash):
            return None

        if needs_rehash(user.password_hash):
            try:
                user.password_hash = await hash_password_async(password)
                await self._repo.update_user(user)
            except Exception:
                # 重哈希只是机会性升级；暂时的数据库错误不能阻止本应成功的登录。
                logger.warning("Failed to rehash password for user %s; login will still succeed", user.email, exc_info=True)

        return user

    async def get_user(self, user_id: str) -> User | None:
        """按用户 ID 查询用户。"""
        return await self._repo.get_user_by_id(user_id)

    async def create_user(self, email: str, password: str | None = None, system_role: str = "user", needs_setup: bool = False) -> User:
        """创建本地用户，并在提供密码时先安全地计算密码哈希。"""
        password_hash = await hash_password_async(password) if password else None
        user = User(
            email=email,
            password_hash=password_hash,
            system_role=system_role,
            needs_setup=needs_setup,
        )
        return await self._repo.create_user(user)

    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        """按 OAuth 提供者和其用户标识查询用户。"""
        return await self._repo.get_user_by_oauth(provider, oauth_id)

    async def count_users(self) -> int:
        """返回已注册用户总数。"""
        return await self._repo.count_users()

    async def count_admin_users(self) -> int:
        """返回管理员用户数量。"""
        return await self._repo.count_admin_users()

    async def update_user(self, user: User) -> User:
        """更新已有用户。"""
        return await self._repo.update_user(user)

    async def get_user_by_email(self, email: str) -> User | None:
        """按邮箱查询用户。"""
        return await self._repo.get_user_by_email(email)

    async def create_oauth_user(
        self,
        email: str,
        oauth_provider: str,
        oauth_id: str,
        system_role: str = "user",
    ) -> User:
        """根据 OAuth/OIDC 登录身份创建没有本地密码的新用户。"""
        user = User(
            email=email,
            password_hash=None,
            system_role=system_role,
            needs_setup=False,
            oauth_provider=oauth_provider,
            oauth_id=oauth_id,
        )
        return await self._repo.create_user(user)
