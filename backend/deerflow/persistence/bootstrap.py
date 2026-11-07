'''按当前模型初始化业务表并检查已有结构，不创建数据库版本记录。'''

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)
_PG_LOCK_KEY = 0x0DEE_12F1_0BEE_3682


def _ensure_business_schema(connection) -> None:
    '''补齐缺少的业务表，拒绝缺失必要字段的旧结构，并确保索引存在。'''
    from deerflow.persistence.base import Base
    import deerflow.persistence.models  # noqa: F401

    Base.metadata.create_all(connection, checkfirst=True)
    inspector = inspect(connection)
    for table in Base.metadata.sorted_tables:
        actual = {column['name'] for column in inspector.get_columns(table.name)}
        missing = set(table.columns.keys()) - actual
        if missing:
            raise RuntimeError(
                f'数据库表 {table.name} 缺少必要字段 {sorted(missing)}；'
                '当前不记录结构版本，请先显式升级表结构再启动。'
            )
        for index in table.indexes:
            index.create(connection, checkfirst=True)


async def bootstrap_schema(engine: AsyncEngine) -> None:
    '''在同一事务和咨询锁内初始化业务表，不读取或创建迁移版本表。'''
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        await connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _PG_LOCK_KEY})
        await connection.run_sync(_ensure_business_schema)
    logger.info('业务表初始化及结构检查完成，不记录结构版本')
