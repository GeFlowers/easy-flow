'''本地邮箱与密码认证提供者。'''

import logging

from server.gateway.auth.models import User
from server.gateway.auth.password import hash_password_async, needs_rehash, verify_password_async
from server.gateway.auth.providers import AuthProvider
from server.gateway.user_repository import SQLUserRepository

logger = logging.getLogger(__name__)


class LocalAuthProvider(AuthProvider):
    '''使用本地数据库验证邮箱和密码的认证提供者。'''

    def __init__(self, repository: SQLUserRepository):
        '''使用指定的数据库用户仓储初始化认证提供者。'''
        self._repo = repository

    async def authenticate(self, credentials: dict) -> User | None:
        '''使用凭据中的邮箱和密码认证，失败时返回 ``None``。'''
        email = credentials.get("email")
        password = credentials.get("password")

        if not email or not password:
            return None

        user = await self._repo.get_user_by_email(email)
        if user is None:
            return None

        if user.password_hash is None:
            # 未设置本地密码的账户不能通过密码流程登录。
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
        '''按用户 ID 查询用户。'''
        return await self._repo.get_user_by_id(user_id)

    async def create_user(self, email: str, password: str | None = None, system_role: str = "user", needs_setup: bool = False) -> User:
        '''创建本地用户，并在提供密码时先安全地计算密码哈希。'''
        password_hash = await hash_password_async(password) if password else None
        user = User(
            email=email,
            password_hash=password_hash,
            system_role=system_role,
            needs_setup=needs_setup,
        )
        return await self._repo.create_user(user)

    async def count_users(self) -> int:
        '''返回已注册用户总数。'''
        return await self._repo.count_users()

    async def count_admin_users(self) -> int:
        '''返回管理员用户数量。'''
        return await self._repo.count_admin_users()

    async def update_user(self, user: User) -> User:
        '''更新已有用户。'''
        return await self._repo.update_user(user)

    async def get_user_by_email(self, email: str) -> User | None:
        '''按邮箱查询用户。'''
        return await self._repo.get_user_by_email(email)
