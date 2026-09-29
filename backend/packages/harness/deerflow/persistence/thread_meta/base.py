"""提供持久化层的模型、仓储、迁移与数据库辅助实现。"""

from __future__ import annotations

import abc
from typing import Any

from deerflow.runtime.user_context import AUTO, _AutoSentinel


class InvalidMetadataFilterError(ValueError):
    """定义持久化层使用的数据模型、配置或辅助组件。"""


class ThreadMetaStore(abc.ABC):
    """定义持久化存储的抽象接口或具体实现。"""

    @abc.abstractmethod
    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
        display_name: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """创建记录并在成功后提交相应的持久化事务。"""
        pass

    @abc.abstractmethod
    async def get(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """按给定条件查询并返回对应的持久化记录。"""
        pass

    @abc.abstractmethod
    async def search(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """查询并返回满足给定条件的持久化记录集合。"""
        pass

    @abc.abstractmethod
    async def update_display_name(self, thread_id: str, display_name: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """更新指定持久化记录的状态或字段并提交事务。"""
        pass

    @abc.abstractmethod
    async def update_status(self, thread_id: str, status: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """更新指定持久化记录的状态或字段并提交事务。"""
        pass

    @abc.abstractmethod
    async def update_metadata(self, thread_id: str, metadata: dict, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """更新指定持久化记录的状态或字段并提交事务。"""
        pass

    @abc.abstractmethod
    async def update_owner(self, thread_id: str, owner_user_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """更新指定持久化记录的状态或字段并提交事务。"""
        pass

    @abc.abstractmethod
    async def check_access(self, thread_id: str, user_id: str, *, require_existing: bool = False) -> bool:
        """判断用户是否拥有线程，并按 require_existing 决定缺失线程是否通过。"""
        pass

    @abc.abstractmethod
    async def delete(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """删除或撤销满足条件的持久化记录并提交事务。"""
        pass
