'''

基于 SQLAlchemy 的 RunEventStore 实现。

将事件持久化到 ``run_events`` 表，并按 ``max_trace_content`` 字节上限
截断追踪内容，避免数据库体积膨胀。
'''

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.models.run_event import RunEventRow
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.user_context import AUTO, _AutoSentinel, get_current_user, resolve_user_id
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class DbRunEventStore(RunEventStore):

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, max_trace_content: int = 10240):
        '''初始化 PostgreSQL 事件仓储及单进程内按线程排序写入的锁。'''
        self._sf = session_factory
        self._max_trace_content = max_trace_content
        self._write_locks: dict[str, asyncio.Lock] = {}

    def _get_write_lock(self, thread_id: str) -> asyncio.Lock:
        '''获取或创建该线程分配事件序号时使用的协程锁。'''
        lock = self._write_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._write_locks[thread_id] = lock
        return lock

    @staticmethod
    def _row_to_dict(row: RunEventRow) -> dict:
        '''将数据库事件行还原为 API 格式，并恢复 JSON 内容及 UTC 时间。'''
        d = row.to_dict()
        d["metadata"] = d.pop("event_metadata", {})
        val = d.get("created_at")
        if isinstance(val, datetime):
            # 兼容历史无时区时间，输出前统一补上 UTC 偏移。
            d["created_at"] = coerce_iso(val)
        d.pop("id", None)
        raw = d.get("content", "")
        metadata = d.get("metadata", {})
        if isinstance(raw, str) and (metadata.get("content_is_json") or metadata.get("content_is_dict")):
            try:
                d["content"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                logger.debug("Failed to deserialize content as JSON for event seq=%s", d.get("seq"))
        return d

    def _truncate_trace(self, category: str, content: Any, metadata: dict | None) -> tuple[Any, dict]:
        '''按字节上限截断 trace 正文，并在元数据中记录截断事实。'''
        if category == "trace":
            text = content if isinstance(content, str) else json.dumps(content, default=str, ensure_ascii=False)
            encoded = text.encode("utf-8")
            if len(encoded) > self._max_trace_content:
                content = encoded[: self._max_trace_content].decode("utf-8", errors="ignore")
                metadata = {**(metadata or {}), "content_truncated": True, "original_byte_length": len(encoded)}
        return content, metadata or {}

    @staticmethod
    def _content_to_db(content: Any, metadata: dict | None) -> tuple[str, dict]:
        '''把结构化事件内容编码为文本，并标记读取时所需的反序列化信息。'''
        metadata = metadata or {}
        if isinstance(content, str):
            return content, metadata

        db_content = json.dumps(content, default=str, ensure_ascii=False)
        metadata = {**metadata, "content_is_json": True}
        if isinstance(content, dict):
            metadata["content_is_dict"] = True
        return db_content, metadata

    @staticmethod
    def _user_id_from_context() -> str | None:
        '''从请求上下文读取用户 ID 并转成数据库字符串；后台写入可没有用户上下文。'''
        user = get_current_user()
        return str(user.id) if user is not None else None

    @staticmethod
    async def _max_seq_for_thread(session: AsyncSession, thread_id: str) -> int | None:
        '''在事务锁保护下读取线程最大事件序号，供并发写入安全分配下一个序号。'''
        stmt = select(func.max(RunEventRow.seq)).where(RunEventRow.thread_id == thread_id)
        bind = session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        if dialect_name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(CAST(:thread_id AS text))::bigint)"),
                {"thread_id": thread_id},
            )
            return await session.scalar(stmt)

        return await session.scalar(stmt.with_for_update())

    async def put(self, *, thread_id, run_id, event_type, category, content="", metadata=None, created_at=None):  # noqa: D401
        '''写入单条事件并在事务中分配线程级递增序号。'''
        content, metadata = self._truncate_trace(category, content, metadata)
        db_content, metadata = self._content_to_db(content, metadata)
        user_id = self._user_id_from_context()
        async with self._get_write_lock(thread_id):
            async with self._sf() as session:
                async with session.begin():
                    max_seq = await self._max_seq_for_thread(session, thread_id)
                    seq = (max_seq or 0) + 1
                    row = RunEventRow(
                        thread_id=thread_id,
                        run_id=run_id,
                        user_id=user_id,
                        event_type=event_type,
                        category=category,
                        content=db_content,
                        event_metadata=metadata,
                        seq=seq,
                        created_at=datetime.fromisoformat(created_at) if created_at else datetime.now(UTC),
                    )
                    session.add(row)
                return self._row_to_dict(row)

    async def put_batch(self, events):
        '''将同一线程的一批事件写入数据库，并在一次事务中连续分配序号。'''
        if not events:
            return []
        thread_ids = {e["thread_id"] for e in events}
        if len(thread_ids) > 1:
            raise ValueError(f"put_batch requires all events to belong to the same thread; got {thread_ids!r}")
        user_id = self._user_id_from_context()
        thread_id = events[0]["thread_id"]
        async with self._get_write_lock(thread_id):
            async with self._sf() as session:
                async with session.begin():
                    max_seq = await self._max_seq_for_thread(session, thread_id)
                    seq = max_seq or 0
                    rows = []
                    for e in events:
                        seq += 1
                        content = e.get("content", "")
                        category = e.get("category", "trace")
                        metadata = e.get("metadata")
                        content, metadata = self._truncate_trace(category, content, metadata)
                        db_content, metadata = self._content_to_db(content, metadata)
                        row = RunEventRow(
                            thread_id=e["thread_id"],
                            run_id=e["run_id"],
                            user_id=e.get("user_id", user_id),
                            event_type=e["event_type"],
                            category=category,
                            content=db_content,
                            event_metadata=metadata,
                            seq=seq,
                            created_at=datetime.fromisoformat(e["created_at"]) if e.get("created_at") else datetime.now(UTC),
                        )
                        session.add(row)
                        rows.append(row)
                return [self._row_to_dict(r) for r in rows]

    async def list_messages(
        self,
        thread_id,
        *,
        limit=50,
        before_seq=None,
        after_seq=None,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        '''按线程及可选游标分页读取消息，结果保持事件序号升序。'''
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.list_messages")
        stmt = select(RunEventRow).where(RunEventRow.thread_id == thread_id, RunEventRow.category == "message")
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        if before_seq is not None:
            stmt = stmt.where(RunEventRow.seq < before_seq)
        if after_seq is not None:
            stmt = stmt.where(RunEventRow.seq > after_seq)

        if after_seq is not None:
            stmt = stmt.order_by(RunEventRow.seq.asc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                return [self._row_to_dict(r) for r in result.scalars()]
        else:
            stmt = stmt.order_by(RunEventRow.seq.desc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars())
                return [self._row_to_dict(r) for r in reversed(rows)]

    async def list_events(
        self,
        thread_id,
        run_id,
        *,
        event_types=None,
        task_id=None,
        limit=500,
        after_seq=None,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        '''读取指定运行的事件，可按事件类型、子任务和序号游标筛选。'''
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.list_events")
        stmt = select(RunEventRow).where(RunEventRow.thread_id == thread_id, RunEventRow.run_id == run_id)
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        if event_types:
            stmt = stmt.where(RunEventRow.event_type.in_(event_types))
        if task_id is not None:
            stmt = stmt.where(RunEventRow.event_metadata["task_id"].as_string() == task_id)
        if after_seq is not None:
            stmt = stmt.where(RunEventRow.seq > after_seq)
        stmt = stmt.order_by(RunEventRow.seq.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_messages_by_run(
        self,
        thread_id,
        run_id,
        *,
        limit=50,
        before_seq=None,
        after_seq=None,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        '''按运行 ID 分页读取消息，并支持向前或向后游标查询。'''
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.list_messages_by_run")
        stmt = select(RunEventRow).where(
            RunEventRow.thread_id == thread_id,
            RunEventRow.run_id == run_id,
            RunEventRow.category == "message",
        )
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        if before_seq is not None:
            stmt = stmt.where(RunEventRow.seq < before_seq)
        if after_seq is not None:
            stmt = stmt.where(RunEventRow.seq > after_seq)

        if after_seq is not None:
            stmt = stmt.order_by(RunEventRow.seq.asc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                return [self._row_to_dict(r) for r in result.scalars()]
        else:
            stmt = stmt.order_by(RunEventRow.seq.desc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars())
                return [self._row_to_dict(r) for r in reversed(rows)]

    async def get_last_visible_ai_seq_by_run(
        self,
        thread_id,
        run_ids,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        '''批量返回每个运行最后一条用户可见助手回复的事件序号。'''
        if not run_ids:
            return {}
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.get_last_visible_ai_seq_by_run")
        caller = RunEventRow.event_metadata["caller"].as_string()
        stmt = (
            select(RunEventRow.run_id, func.max(RunEventRow.seq))
            .where(
                RunEventRow.thread_id == thread_id,
                RunEventRow.run_id.in_(run_ids),
                RunEventRow.category == "message",
                RunEventRow.event_type.in_(("llm.ai.response", "ai_message")),
                ~func.coalesce(caller, "").like("middleware:%"),
            )
            .group_by(RunEventRow.run_id)
        )
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {run_id: seq for run_id, seq in result if isinstance(seq, int)}

    async def count_messages(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        '''统计指定线程中符合用户作用域的消息记录数。'''
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.count_messages")
        stmt = select(func.count()).select_from(RunEventRow).where(RunEventRow.thread_id == thread_id, RunEventRow.category == "message")
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        async with self._sf() as session:
            return await session.scalar(stmt) or 0

    async def delete_by_thread(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        '''删除线程事件并返回删除数，同时回收空闲的序号锁。'''
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.delete_by_thread")
        async with self._sf() as session:
            count_conditions = [RunEventRow.thread_id == thread_id]
            if resolved_user_id is not None:
                count_conditions.append(RunEventRow.user_id == resolved_user_id)
            count_stmt = select(func.count()).select_from(RunEventRow).where(*count_conditions)
            count = await session.scalar(count_stmt) or 0
            if count > 0:
                await session.execute(delete(RunEventRow).where(*count_conditions))
                await session.commit()
            lock = self._write_locks.get(thread_id)
            if lock is not None and not lock.locked():
                self._write_locks.pop(thread_id, None)
            return count

    async def delete_by_run(
        self,
        thread_id,
        run_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        '''删除指定运行在给定线程中的事件并返回删除数。'''
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.delete_by_run")
        async with self._sf() as session:
            count_conditions = [RunEventRow.thread_id == thread_id, RunEventRow.run_id == run_id]
            if resolved_user_id is not None:
                count_conditions.append(RunEventRow.user_id == resolved_user_id)
            count_stmt = select(func.count()).select_from(RunEventRow).where(*count_conditions)
            count = await session.scalar(count_stmt) or 0
            if count > 0:
                await session.execute(delete(RunEventRow).where(*count_conditions))
                await session.commit()
            return count
