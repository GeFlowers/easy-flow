'''抽象数据库操作的用户仓储接口。'''

from abc import ABC, abstractmethod

from app.gateway.auth.models import User


class UserNotFoundError(LookupError):
    '''当用户仓储操作指向不存在的行时抛出。

    继承 :class:`LookupError` 以保持现有缺失实体处理兼容，同时让调用方能将
    更新期间的并发删除与其他查询未命中区分开。
    '''


class UserRepository(ABC):
    '''定义 Gateway 用户仓储必须实现的持久化操作。'''

    @abstractmethod
    async def create_user(self, user: User) -> User:
        '''创建用户；邮箱已存在时抛出 ``ValueError``。'''
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> User | None:
        '''按用户 UUID 字符串查询用户，未找到时返回 ``None``。'''
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_email(self, email: str) -> User | None:
        '''按邮箱查询用户，未找到时返回 ``None``。'''
        raise NotImplementedError

    @abstractmethod
    async def update_user(self, user: User) -> User:
        '''更新已有用户；目标行不存在时以 ``UserNotFoundError`` 失败。

        该失败不是静默空操作，防止调用方把并发删除误认为更新成功。
        '''
        raise NotImplementedError

    @abstractmethod
    async def count_users(self) -> int:
        '''返回已注册用户总数。'''
        raise NotImplementedError

    @abstractmethod
    async def count_admin_users(self) -> int:
        '''返回 ``system_role`` 为 ``admin`` 的用户数量。'''
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        '''按 OAuth 提供者及其用户标识查询用户，未找到时返回 ``None``。'''
        raise NotImplementedError
