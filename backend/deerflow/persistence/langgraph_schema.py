'''维护当前 LangGraph PostgreSQL 数据表结构，替代依赖版本表的初始化。'''

from __future__ import annotations

from typing import Literal

SchemaKind = Literal['checkpoint', 'store']
_SCHEMA_LOCK_KEY = 0x0DEE_12F1_0BEE_3683
_COMPATIBLE_DRIVER_VERSION = '3.0.5'

# 结构与当前检查点和存储适配器兼容；升级适配器时须同步验证结构。
CHECKPOINT_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT,
        type TEXT,
        checkpoint JSONB NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )''',
    '''CREATE TABLE IF NOT EXISTS checkpoint_blobs (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL,
        version TEXT NOT NULL,
        type TEXT NOT NULL,
        blob BYTEA,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS checkpoint_writes (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        channel TEXT NOT NULL,
        type TEXT,
        blob BYTEA NOT NULL,
        task_path TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    )''',
    'ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP NOT NULL',
    "ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT ''",
    'CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id)',
    'CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id)',
    'CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id)',
)

STORE_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS store (
        prefix TEXT NOT NULL,
        key TEXT NOT NULL,
        value JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP WITH TIME ZONE,
        ttl_minutes INT,
        PRIMARY KEY (prefix, key)
    )''',
    'ALTER TABLE store ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE',
    'ALTER TABLE store ADD COLUMN IF NOT EXISTS ttl_minutes INT',
    'CREATE INDEX IF NOT EXISTS store_prefix_idx ON store USING btree (prefix text_pattern_ops)',
    'CREATE INDEX IF NOT EXISTS idx_store_expires_at ON store (expires_at) WHERE expires_at IS NOT NULL',
)

# 修改前先查询实际字段，避免每次启动都申请不必要的排他表锁。
_COLUMN_CHANGES = {
    CHECKPOINT_STATEMENTS[3]: ('checkpoint_blobs', 'blob', 'nullable'),
    CHECKPOINT_STATEMENTS[4]: ('checkpoint_writes', 'task_path', 'add'),
    STORE_STATEMENTS[1]: ('store', 'expires_at', 'add'),
    STORE_STATEMENTS[2]: ('store', 'ttl_minutes', 'add'),
}
_COLUMN_QUERY = '''SELECT is_nullable FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s'''


def needs_column_change(operation: str, existing: tuple[str] | None) -> bool:
    '''判断字段是否确需变更；未知操作或缺失必需字段时明确报错。'''
    if operation == 'add':
        return existing is None
    if operation == 'nullable':
        if existing is None:
            raise RuntimeError('检查点结构缺少必要的二进制数据字段，请显式升级结构。')
        return existing[0] == 'NO'
    raise ValueError(f'未知字段变更操作：{operation}')


def _check_driver_compatibility() -> None:
    '''阻止未经验证的存储依赖升级静默使用旧结构，不写入数据库版本表。'''
    from importlib.metadata import version

    installed = version('langgraph-checkpoint-postgres')
    if installed != _COMPATIBLE_DRIVER_VERSION:
        raise RuntimeError(
            f'当前无版本表结构适配 langgraph-checkpoint-postgres {_COMPATIBLE_DRIVER_VERSION}，'
            f'实际为 {installed}；请验证并同步维护结构后再升级依赖。'
        )


def _statements(kind: SchemaKind) -> tuple[str, ...]:
    '''按明确的存储类型选取结构声明，拒绝未知类型。'''
    if kind == 'checkpoint':
        return CHECKPOINT_STATEMENTS
    if kind == 'store':
        return STORE_STATEMENTS
    raise ValueError(f'不支持的数据库结构类型：{kind}')


def ensure_langgraph_schema(connection_string: str, kind: SchemaKind) -> None:
    '''同步补齐数据结构；整个初始化在同一事务和咨询锁内执行。'''
    from psycopg import connect

    _check_driver_compatibility()
    statements = _statements(kind)
    with connect(connection_string, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (_SCHEMA_LOCK_KEY,))
            for statement in statements:
                if change := _COLUMN_CHANGES.get(statement):
                    table, column, operation = change
                    cursor.execute(_COLUMN_QUERY, (table, column))
                    if not needs_column_change(operation, cursor.fetchone()):
                        continue
                cursor.execute(statement)


async def ensure_langgraph_schema_async(connection_string: str, kind: SchemaKind) -> None:
    '''异步补齐同一份结构，不调用会重建版本表的第三方初始化方法。'''
    from psycopg import AsyncConnection

    _check_driver_compatibility()
    statements = _statements(kind)
    async with await AsyncConnection.connect(connection_string, connect_timeout=10) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute("SET LOCAL lock_timeout = '5s'")
            await cursor.execute('SELECT pg_advisory_xact_lock(%s)', (_SCHEMA_LOCK_KEY,))
            for statement in statements:
                if change := _COLUMN_CHANGES.get(statement):
                    table, column, operation = change
                    await cursor.execute(_COLUMN_QUERY, (table, column))
                    if not needs_column_change(operation, await cursor.fetchone()):
                        continue
                await cursor.execute(statement)
