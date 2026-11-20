'''由 SQLAlchemy 支持的用户仓储。

该仓储使用 ``deerflow.persistence.engine`` 的共享异步会话工厂，``users`` 表
与 ``threads_meta``、``runs``、``run_events`` 和 ``feedback`` 共用数据库。
调用方须在 ``init_engine_from_config()`` 后传入会话工厂构造本仓储。
'''

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.user.model import UserRow

if TYPE_CHECKING:
    from server.gateway.auth.models import User


class UserNotFoundError(LookupError):
    '''更新的用户行已不存在，区别于普通查询未命中。'''


class SQLUserRepository:
    '''由共享 SQLAlchemy 引擎支持的异步用户仓储。'''

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        '''保存用于创建独立异步数据库会话的会话工厂。'''
        self._sf = session_factory

    # ── 增删改查 ──────────────────────────────────────────────────────

    async def create_user(self, user: User) -> User:
        '''插入新用户；邮箱重复时抛出 ``ValueError``。'''
        row = self._user_to_row(user)
        async with self._sf() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError(f"Email already registered: {user.email}") from exc
        return user

    @staticmethod
    def _user_to_row(user: User) -> UserRow:
        '''将应用层 ``User`` 模型转换为可持久化的 ``UserRow``。'''
        return UserRow(
            id=str(user.id),
            email=user.email,
            password_hash=user.password_hash,
            system_role=user.system_role,
            created_at=user.created_at,
            needs_setup=user.needs_setup,
            token_version=user.token_version,
        )

    async def get_user_by_id(self, user_id: str) -> User | None:
        '''按用户 ID 查询并转换用户；不存在时返回 ``None``。'''
        async with self._sf() as session:
            row = await session.get(UserRow, user_id)
            return self._row_to_user(row) if row is not None else None

    # ── 模型转换 ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_user(row: UserRow) -> User:
        '''将持久化 ``UserRow`` 转换为应用层 ``User`` 模型。'''
        # 延迟导入，避免认证包加载提供者时与仓储形成循环依赖。
        from server.gateway.auth.models import User

        return User(
            id=UUID(row.id),
            email=row.email,
            password_hash=row.password_hash,
            system_role=row.system_role,  # type: ignore[arg-type]
            # 数据库读取时间时会丢失时区；补回协调世界时以便下游可靠比较时间戳。
            created_at=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC),
            needs_setup=row.needs_setup,
            token_version=row.token_version,
        )

    async def get_user_by_email(self, email: str) -> User | None:
        '''按邮箱查询并转换用户；不存在时返回 ``None``。'''
        stmt = select(UserRow).where(UserRow.email == email)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_user(row) if row is not None else None

    async def update_user(self, user: User) -> User:
        '''更新用户行；若行已被并发删除则明确抛出 ``UserNotFoundError``。'''
        async with self._sf() as session:
            row = await session.get(UserRow, str(user.id))
            if row is None:
                # 并发删除必须硬失败：调用方在本调用前刚查询过用户，故此处缺行
                # 表示目标已在其间消失。静默成功会让调用方记录并不存在行的
                # “密码已重置”，破坏操作结果的真实性。
                raise UserNotFoundError(f"User {user.id} no longer exists")
            row.email = user.email
            row.password_hash = user.password_hash
            row.system_role = user.system_role
            row.needs_setup = user.needs_setup
            row.token_version = user.token_version
            await session.commit()
        return user

    async def count_users(self) -> int:
        '''统计用户表中的全部用户数量。'''
        stmt = select(func.count()).select_from(UserRow)
        async with self._sf() as session:
            return await session.scalar(stmt) or 0

    async def count_admin_users(self) -> int:
        '''统计角色为管理员的用户数量。'''
        stmt = select(func.count()).select_from(UserRow).where(UserRow.system_role == "admin")
        async with self._sf() as session:
            return await session.scalar(stmt) or 0
