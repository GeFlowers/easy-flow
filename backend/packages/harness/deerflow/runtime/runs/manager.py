'''管理进程内活跃运行，并把运行记录持久化到 PostgreSQL RunStore。'''

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError as SAIntegrityError

from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import is_lease_expired
from deerflow.utils.time import now_iso as _now_iso

from .schemas import DisconnectMode, RunStatus

if TYPE_CHECKING:
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.runtime.runs.store import RunStore

logger = logging.getLogger(__name__)

# 用于识别数据库冲突类型的 PostgreSQL SQLSTATE 状态码。
_UNIQUE_PGCODE = "23505"
_RETRYABLE_POSTGRES_STATES = {"40001", "40P01"}


def _generate_worker_id() -> str:
    '''生成包含主机名和随机值的工作进程唯一标识。'''
    return f"{socket.gethostname()}:{uuid.uuid4().hex}"


def _is_unique_violation(exc: BaseException) -> bool:
    '''检查异常及其包装原因，识别 PostgreSQL 唯一键冲突。'''
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        if getattr(current, "pgcode", None) == _UNIQUE_PGCODE:
            return True
        if getattr(current, "sqlcode", None) == _UNIQUE_PGCODE:
            return True
        if getattr(current, "sqlstate", None) == _UNIQUE_PGCODE:
            return True
        # 某些数据库驱动无法从异常链中取得原生错误码，因此同时检查错误消息作为兜底。
        # 必须确认异常节点属于 IntegrityError，避免应用异常仅因文本包含 "duplicate key"、
        # "unique" 和 "violat"（例如检查约束错误、校验错误或其他子系统消息）就被误判为唯一键冲突，
        # 并错误地返回 HTTP 409 而不是 500。
        if isinstance(current, SAIntegrityError):
            message = str(current).lower()
            if "unique" in message and "violat" in message:
                return True
            if "duplicate key" in message:
                return True

        for attr in ("orig", "__cause__", "__context__"):
            inner = getattr(current, attr, None)
            if isinstance(inner, BaseException):
                pending.append(inner)
    return False


def _is_retryable_persistence_error(exc: BaseException) -> bool:
    '''识别 PostgreSQL 可安全重试的事务序列化冲突和死锁。'''

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        if getattr(current, "sqlstate", None) in _RETRYABLE_POSTGRES_STATES:
            return True
        if getattr(current, "pgcode", None) in _RETRYABLE_POSTGRES_STATES:
            return True
        for chained in (getattr(current, "orig", None), current.__cause__, current.__context__):
            if isinstance(chained, BaseException):
                pending.append(chained)
    return False


@dataclass(frozen=True)
class PersistenceRetryPolicy:
    '''限制短事务重试次数和退避时间，防止冲突让运行管理无限等待。'''

    max_attempts: int = 5
    initial_delay: float = 0.05
    max_delay: float = 1.0
    backoff_factor: float = 2.0


@dataclass
class RunRecord:
    '''

    Mutable record for a single run.'''

    run_id: str
    thread_id: str
    assistant_id: str | None
    status: RunStatus
    on_disconnect: DisconnectMode
    multitask_strategy: str = "reject"
    metadata: dict = field(default_factory=dict)
    kwargs: dict = field(default_factory=dict)
    user_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)
    abort_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    abort_action: str = "interrupt"
    error: str | None = None
    model_name: str | None = None
    store_only: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    llm_call_count: int = 0
    lead_agent_tokens: int = 0
    subagent_tokens: int = 0
    middleware_tokens: int = 0
    token_usage_by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    message_count: int = 0
    last_ai_message: str | None = None
    first_human_message: str | None = None
    finalizing: bool = False
    owner_worker_id: str | None = None
    lease_expires_at: str | None = None
    stop_reason: str | None = None


class RunManager:
    '''协调活跃运行、取消信号、跨进程租约及持久化运行历史。'''

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        persistence_retry_policy: PersistenceRetryPolicy | None = None,
        worker_id: str | None = None,
        run_ownership_config: RunOwnershipConfig | None = None,
    ) -> None:
        '''初始化运行注册表、持久化仓储以及跨进程所有权参数。'''
        self._runs: dict[str, RunRecord] = {}
        # 辅助索引：thread_id 映射到按插入顺序排列的 run_id 集合（用字典实现有序集合）。
        # 与 ``_runs`` 同步维护，避免按线程查询时扫描全部内存运行记录，同时保留 ``_runs`` 的迭代顺序
        #（见 ``_thread_records_locked``）。
        self._runs_by_thread: dict[str, dict[str, None]] = {}
        self._lock = asyncio.Lock()
        self._store = store
        self._persistence_retry_policy = persistence_retry_policy or PersistenceRetryPolicy()
        self._worker_id = worker_id or _generate_worker_id()
        self._run_ownership_config = run_ownership_config
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_stop: asyncio.Event | None = None

    def _index_run_locked(self, record: RunRecord) -> None:
        '''

        将运行记录加入线程索引；调用方需先持有实例锁。'''
        self._runs_by_thread.setdefault(record.thread_id, {})[record.run_id] = None

    def _unindex_run_locked(self, run_id: str, thread_id: str) -> None:
        '''

        从线程索引移除运行 ID；调用方需先持有实例锁。'''
        bucket = self._runs_by_thread.get(thread_id)
        if bucket is not None:
            bucket.pop(run_id, None)
            if not bucket:
                self._runs_by_thread.pop(thread_id, None)

    def _thread_records_locked(self, thread_id: str) -> list[RunRecord]:
        '''

        返回：live in-memory records for *thread_id*. Caller must hold ``self._lock``.

                Uses the ``_runs_by_thread`` index for O(runs-in-thread) lookup instead of
                scanning every in-memory run. Correctness rests on the index and ``_runs``
                being mutated in lockstep under ``self._lock`` (no ``await`` between the two
                writes), so any holder of the lock sees them agree. The ``self._runs.get``
                filter is defense-in-depth, not reconciliation: it drops a stale id still in
                the index but already gone from ``_runs``, yet it cannot recover a run that is
                in ``_runs`` but missing from the index (such a run would be silently
                omitted). It guards only that one direction, should a future refactor ever
                break the lockstep invariant.
        '''
        run_ids = self._runs_by_thread.get(thread_id)
        if not run_ids:
            return []
        return [record for run_id in run_ids if (record := self._runs.get(run_id)) is not None]

    @staticmethod
    def _store_put_payload(record: RunRecord, *, error: str | None = None, stop_reason: str | None = None) -> dict[str, Any]:
        '''将运行记录转换为 RunStore 接受的字段，并合并最终错误与停止原因。'''
        payload = {
            "thread_id": record.thread_id,
            "assistant_id": record.assistant_id,
            "status": record.status.value,
            "multitask_strategy": record.multitask_strategy,
            "metadata": record.metadata or {},
            "kwargs": record.kwargs or {},
            "error": error if error is not None else record.error,
            "created_at": record.created_at,
            "model_name": record.model_name,
            "owner_worker_id": record.owner_worker_id,
            "lease_expires_at": record.lease_expires_at,
        }
        if record.user_id is not None:
            payload["user_id"] = record.user_id
        if record.stop_reason is not None:
            payload["stop_reason"] = record.stop_reason
        return payload

    async def _call_store_with_retry(
        self,
        operation_name: str,
        run_id: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        '''遇到 PostgreSQL 可恢复事务冲突时有限重试存储操作。'''
        policy = self._persistence_retry_policy
        attempt = 1
        delay = policy.initial_delay
        while True:
            try:
                return await operation()
            except Exception as exc:
                retryable = _is_retryable_persistence_error(exc)
                if attempt >= policy.max_attempts or not retryable:
                    raise
                logger.warning(
                    "Transient persistence failure during %s for run %s (attempt %d/%d); retrying",
                    operation_name,
                    run_id,
                    attempt,
                    policy.max_attempts,
                    exc_info=True,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                delay = min(policy.max_delay, delay * policy.backoff_factor if delay else policy.initial_delay)
                attempt += 1

    async def _persist_snapshot_to_store(self, run_id: str, payload: dict[str, Any]) -> bool:
        '''

        尝试将已捕获的运行快照写入持久化仓储。'''
        if self._store is None:
            return True
        try:
            await self._call_store_with_retry(
                "put",
                run_id,
                lambda: self._store.put(run_id, **payload),
            )
            return True
        except Exception:
            logger.warning("Failed to persist run %s to store", run_id, exc_info=True)
            return False

    async def _persist_new_run_to_store(self, record: RunRecord) -> None:
        '''

        持久化：a newly created run record to the backing store.

                Initial run creation is part of the run visibility boundary: callers
                should not observe a run in memory unless its backing store row exists.
                Unlike follow-up status/model updates, failures are propagated so the
                caller can treat creation as failed. Rollback is the caller's
                responsibility after inserting the record into ``_runs``.
        '''
        if self._store is None:
            return
        await self._call_store_with_retry(
            "put",
            record.run_id,
            lambda: self._store.put(record.run_id, **self._store_put_payload(record)),
        )

    async def _persist_to_store(self, record: RunRecord, *, error: str | None = None) -> bool:
        '''

        尝试把运行记录同步到 PostgreSQL 仓储。'''
        return await self._persist_snapshot_to_store(
            record.run_id,
            self._store_put_payload(record, error=error),
        )

    async def _persist_status(self, record: RunRecord, status: RunStatus, *, error: str | None = None, stop_reason: str | None = None) -> bool:
        '''

        尝试持久化运行状态变更并处理短暂数据库冲突。'''
        if self._store is None:
            return True
        row_recovery_payload = self._store_put_payload(record, error=error, stop_reason=stop_reason)
        try:
            updated = await self._call_store_with_retry(
                "update_status",
                record.run_id,
                lambda: self._store.update_status(record.run_id, status.value, error=error, stop_reason=stop_reason),
            )
            if updated is False:
                # ``update_status`` 现在只更新状态为 pending 或 running 的记录。返回 False 可能表示：
                #   (a) 记录从未成功写入（首次 ``put()`` 失败）→ 重新创建。
                #   (b) 记录已进入终态：可能被其他工作器接管并标记为 ``error``，也可能因本地取消与完成竞态
                #       变为 ``interrupted`` 或 ``success``。下方会根据具体状态选择日志级别。
                existing = await self._store.get(record.run_id)
                if existing is not None:
                    existing_status = existing.get("status")
                    if existing_status == "error":
                        logger.warning(
                            "Run %s status update to %s skipped: store row already at error (peer takeover)",
                            record.run_id,
                            status.value,
                        )
                    else:
                        logger.info(
                            "Run %s status update to %s skipped: store row already at %s (local cancel/completion race)",
                            record.run_id,
                            status.value,
                            existing_status,
                        )
                    return False
                return await self._persist_snapshot_to_store(record.run_id, row_recovery_payload)
            return True
        except Exception:
            logger.warning("Failed to persist status update for run %s", record.run_id, exc_info=True)
            return False

    @staticmethod
    def _record_from_store(row: dict[str, Any]) -> RunRecord:
        '''

        构建：a read-only runtime record from a serialized store row.

                NULL status/on_disconnect columns (e.g. from rows written before those
                columns were added) default to ``pending`` and ``cancel`` respectively.
        '''
        return RunRecord(
            run_id=row["run_id"],
            thread_id=row["thread_id"],
            assistant_id=row.get("assistant_id"),
            status=RunStatus(row.get("status") or RunStatus.pending.value),
            on_disconnect=DisconnectMode(row.get("on_disconnect") or DisconnectMode.cancel.value),
            multitask_strategy=row.get("multitask_strategy") or "reject",
            metadata=row.get("metadata") or {},
            kwargs=row.get("kwargs") or {},
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
            user_id=row.get("user_id"),
            error=row.get("error"),
            model_name=row.get("model_name"),
            store_only=True,
            total_input_tokens=row.get("total_input_tokens") or 0,
            total_output_tokens=row.get("total_output_tokens") or 0,
            total_tokens=row.get("total_tokens") or 0,
            llm_call_count=row.get("llm_call_count") or 0,
            lead_agent_tokens=row.get("lead_agent_tokens") or 0,
            subagent_tokens=row.get("subagent_tokens") or 0,
            middleware_tokens=row.get("middleware_tokens") or 0,
            token_usage_by_model=row.get("token_usage_by_model") or {},
            message_count=row.get("message_count") or 0,
            last_ai_message=row.get("last_ai_message"),
            first_human_message=row.get("first_human_message"),
            owner_worker_id=row.get("owner_worker_id"),
            lease_expires_at=row.get("lease_expires_at"),
            stop_reason=row.get("stop_reason"),
        )

    async def update_run_completion(self, run_id: str, **kwargs) -> None:
        '''

        持久化：token usage and completion data to the backing store.'''
        row_recovery_payload: dict[str, Any] | None = None
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                for key, value in kwargs.items():
                    if key == "status":
                        continue
                    if hasattr(record, key) and value is not None:
                        setattr(record, key, value)
                record.updated_at = _now_iso()
                row_recovery_payload = self._store_put_payload(record, error=kwargs.get("error"))
        if self._store is None:
            return
        try:
            updated = await self._call_store_with_retry(
                "update_run_completion",
                run_id,
                lambda: self._store.update_run_completion(run_id, **kwargs),
            )
            if updated is False:
                if row_recovery_payload is None:
                    logger.warning("Failed to recreate missing run %s for completion persistence", run_id)
                    return
                if not await self._persist_snapshot_to_store(run_id, row_recovery_payload):
                    return
                recovered = await self._call_store_with_retry(
                    "update_run_completion",
                    run_id,
                    lambda: self._store.update_run_completion(run_id, **kwargs),
                )
                if recovered is False:
                    logger.warning("Run completion update for %s affected no rows after row recreation", run_id)
        except Exception:
            logger.warning("Failed to persist run completion for %s", run_id, exc_info=True)

    async def update_run_progress(self, run_id: str, **kwargs) -> None:
        '''

        持久化：a running token/message snapshot without changing status.'''
        should_persist = True
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                should_persist = record.status == RunStatus.running
            if record is not None and should_persist:
                for key, value in kwargs.items():
                    if hasattr(record, key) and value is not None:
                        setattr(record, key, value)
                record.updated_at = _now_iso()
        if should_persist and self._store is not None:
            try:
                await self._store.update_run_progress(run_id, **kwargs)
            except Exception:
                logger.warning("Failed to persist run progress for %s", run_id, exc_info=True)

    async def create(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode = DisconnectMode.cancel,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
        user_id: str | None = None,
    ) -> RunRecord:
        '''创建待执行记录并注册到当前工作进程；调用方需自行确保线程没有并发运行任务。'''
        run_id = str(uuid.uuid4())
        now = _now_iso()
        lease_expires_at = self._compute_lease_expires_at()
        record = RunRecord(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            status=RunStatus.pending,
            on_disconnect=on_disconnect,
            multitask_strategy=multitask_strategy,
            metadata=metadata or {},
            kwargs=kwargs or {},
            user_id=user_id,
            created_at=now,
            updated_at=now,
            owner_worker_id=self._worker_id,
            lease_expires_at=lease_expires_at,
        )
        async with self._lock:
            self._runs[run_id] = record
            self._index_run_locked(record)
            persisted = False
            try:
                await self._persist_new_run_to_store(record)
                persisted = True
            except Exception:
                logger.warning("Failed to persist run %s; rolled back in-memory record", run_id, exc_info=True)
                raise
            finally:
                if not persisted:
                    self._runs.pop(run_id, None)
                    self._unindex_run_locked(run_id, record.thread_id)
        logger.info("Run created: run_id=%s thread_id=%s", run_id, thread_id)
        return record

    async def get(self, run_id: str, *, user_id: str | None = None) -> RunRecord | None:
        '''

        返回：a run record by ID, or ``None``.

                Args:
                    run_id: The run ID to look up.
                    user_id: Optional user ID for permission filtering when hydrating from store.
        '''
        async with self._lock:
            record = self._runs.get(run_id)
        if record is not None:
            return record
        if self._store is None:
            return None
        try:
            row = await self._store.get(run_id, user_id=user_id)
        except Exception:
            logger.warning("Failed to hydrate run %s from store", run_id, exc_info=True)
            return None
        # 等待存储操作后重新检查：存储调用期间，并发的 create() 可能已插入内存记录。
        async with self._lock:
            record = self._runs.get(run_id)
        if record is not None:
            return record
        if row is None:
            return None
        try:
            return self._record_from_store(row)
        except Exception:
            logger.warning("Failed to map store row for run %s", run_id, exc_info=True)
            return None

    async def aget(self, run_id: str, *, user_id: str | None = None) -> RunRecord | None:
        '''

        返回：a run record by ID, checking the persistent store as fallback.

                Alias for :meth:`get` for backward compatibility.
        '''
        return await self.get(run_id, user_id=user_id)

    async def list_by_thread(self, thread_id: str, *, user_id: str | None = None, limit: int = 100) -> list[RunRecord]:
        '''

        返回：runs for a given thread, newest first, at most ``limit`` records.

                内存实现：runs take precedence only when the same ``run_id`` exists in both
                memory and the backing store. The merged result is then sorted newest-first
                by ``created_at`` and trimmed to ``limit`` (default 100).

                Args:
                    thread_id: The thread ID to filter by.
                    user_id: Optional user ID for permission filtering when hydrating from store.
                    limit: Maximum number of runs to return.
        '''
        async with self._lock:
            memory_records = self._thread_records_locked(thread_id)
        if self._store is None:
            return sorted(memory_records, key=lambda r: r.created_at, reverse=True)[:limit]
        records_by_id = {record.run_id: record for record in memory_records}
        store_limit = max(0, limit - len(memory_records))
        try:
            rows = await self._store.list_by_thread(thread_id, user_id=user_id, limit=store_limit)
        except Exception:
            logger.warning("Failed to hydrate runs for thread %s from store", thread_id, exc_info=True)
            return sorted(memory_records, key=lambda r: r.created_at, reverse=True)[:limit]
        for row in rows:
            run_id = row.get("run_id")
            if run_id and run_id not in records_by_id:
                try:
                    records_by_id[run_id] = self._record_from_store(row)
                except Exception:
                    logger.warning("Failed to map store row for run %s", run_id, exc_info=True)
        return sorted(records_by_id.values(), key=lambda record: record.created_at, reverse=True)[:limit]

    async def list_successful_regenerate_sources(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> set[str]:
        '''

        返回：all source runs superseded by successful regenerations.

                Unlike :meth:`list_by_thread`, this query is intentionally unbounded.
                Current-process records override matching persisted status: a latest
                in-memory failure must not inherit an older successful store snapshot.
                Store failures propagate because supersession filtering is required for
                correct pagination.
        '''
        resolved_user_id = resolve_user_id(user_id, method_name="RunManager.list_successful_regenerate_sources")
        async with self._lock:
            memory_records = [record for record in self._thread_records_locked(thread_id) if resolved_user_id is None or record.user_id == resolved_user_id]

        sources = set(await self._store.list_successful_regenerate_sources(thread_id, user_id=resolved_user_id)) if self._store is not None else set()
        # _thread_records_locked 保留线程索引中的插入顺序。按从旧到新的顺序应用记录，
        # 可确保多个尝试引用同一源运行时，以最近的内存记录为准（例如成功后又进行了一次失败重试）。
        for record in memory_records:
            source = record.metadata.get("regenerate_from_run_id")
            if not isinstance(source, str) or not source:
                continue
            sources.discard(source)
            if record.status == RunStatus.success:
                sources.add(source)
        return sources

    async def get_many_by_thread(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, RunRecord]:
        '''

        批量读取线程运行记录，优先返回内存中较新的记录。'''
        if not run_ids:
            return {}
        resolved_user_id = resolve_user_id(user_id, method_name="RunManager.get_many_by_thread")
        async with self._lock:
            records_by_id = {record.run_id: record for record in self._thread_records_locked(thread_id) if record.run_id in run_ids and (resolved_user_id is None or record.user_id == resolved_user_id)}
        if self._store is None:
            return records_by_id

        remaining = run_ids - records_by_id.keys()
        if not remaining:
            return records_by_id
        try:
            rows = await self._store.get_many_by_thread(thread_id, set(remaining), user_id=resolved_user_id)
        except Exception:
            logger.warning("Failed to batch-hydrate runs for thread %s", thread_id, exc_info=True)
            return records_by_id
        for run_id, row in rows.items():
            if run_id in records_by_id:
                continue
            try:
                records_by_id[run_id] = self._record_from_store(row)
            except Exception:
                logger.warning("Failed to map store row for run %s", run_id, exc_info=True)
        return records_by_id

    async def set_status(self, run_id: str, status: RunStatus, *, error: str | None = None, stop_reason: str | None = None) -> None:
        '''

        更新运行状态及其可选终态字段，并同步状态事件。'''
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_status called for unknown run %s", run_id)
                return
            record.status = status
            record.updated_at = _now_iso()
            if error is not None:
                record.error = error
            if stop_reason is not None:
                record.stop_reason = stop_reason
        await self._persist_status(record, status, error=error, stop_reason=stop_reason)
        logger.info("Run %s -> %s", run_id, status.value)

    async def set_finalizing(self, run_id: str, finalizing: bool) -> None:
        '''

        标记运行是否正在执行取消后的清理流程。'''
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_finalizing called for unknown run %s", run_id)
                return
            record.finalizing = finalizing
            record.updated_at = _now_iso()

    async def wait_for_prior_finalizing(
        self,
        thread_id: str,
        run_id: str,
        *,
        poll_interval: float = 0.01,
    ) -> None:
        '''

        等待同线程较早运行完成取消后的收尾工作。'''
        while True:
            async with self._lock:
                found_current = False
                prior_finalizing = False
                for record in self._thread_records_locked(thread_id):
                    if record.run_id == run_id:
                        found_current = True
                        break
                    if record.finalizing:
                        prior_finalizing = True

                if not found_current or not prior_finalizing:
                    return

            await asyncio.sleep(poll_interval)

    async def has_later_run(self, thread_id: str, run_id: str) -> bool:
        '''判断指定运行记录之后是否已有同一线程的新运行进入内存队列。'''
        async with self._lock:
            seen_current = False
            for record in self._thread_records_locked(thread_id):
                if record.run_id == run_id:
                    seen_current = True
                    continue
                if seen_current:
                    return True
        return False

    async def has_later_started_run(self, thread_id: str, run_id: str) -> bool:
        '''判断指定运行之后是否有新运行已开始或进入收尾阶段，避免继续覆盖线程状态。'''
        async with self._lock:
            seen_current = False
            for record in self._thread_records_locked(thread_id):
                if record.run_id == run_id:
                    seen_current = True
                    continue
                if seen_current and (record.status != RunStatus.pending or record.finalizing):
                    return True
        return False

    async def _persist_model_name(self, run_id: str, model_name: str | None) -> None:
        '''

        尝试将实际解析出的模型名称更新到持久化记录。'''
        if self._store is None:
            return
        try:
            await self._call_store_with_retry(
                "update_model_name",
                run_id,
                lambda: self._store.update_model_name(run_id, model_name),
            )
        except Exception:
            logger.warning("Failed to persist model_name update for run %s", run_id, exc_info=True)

    async def update_model_name(self, run_id: str, model_name: str | None) -> None:
        '''

        更新：the model name for a run.'''
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("update_model_name called for unknown run %s", run_id)
                return
            record.model_name = model_name
            record.updated_at = _now_iso()
        await self._persist_model_name(run_id, model_name)
        logger.info("Run %s model_name=%s", run_id, model_name)

    async def cancel(self, run_id: str, *, action: str = "interrupt") -> CancelOutcome:
        '''

        设置取消信号并更新运行记录，供执行协程安全退出。

                When the call lands on the owning worker the run is cancelled
                locally as before (in-memory abort + status persisted to store).

                When the call lands on a non-owning worker in a multi-worker
                deployment with heartbeat enabled:

                - **Lease expired** — the run's lease has passed the grace
                  threshold, so this worker takes ownership and marks it as
                  ``error``.  The owning worker is assumed dead (its heartbeat
                  stopped renewing).

                - **Lease still valid** — returns ``lease_valid_elsewhere`` so
                  the caller can return HTTP 409 + ``Retry-After`` to tell the
                  client when to retry.

                In single-worker mode (``heartbeat_enabled=False``) store-only
                hydrated runs that aren't in-memory return ``not_active_locally``,
                preserving the original 409 behaviour.

                Args:
                    run_id: The run ID to cancel.
                    action: ``"interrupt"`` keeps checkpoint, ``"rollback"``
                            reverts to pre-run state.

                Returns:
                    A :class:`CancelOutcome` enum describing what happened.
        '''
        # 本地运行路径：当前工作器在内存中拥有该运行。
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                if record.status == RunStatus.interrupted:
                    return CancelOutcome.cancelled
                if record.status not in (RunStatus.pending, RunStatus.running):
                    return CancelOutcome.not_cancellable
                record.abort_action = action
                record.abort_event.set()
                task_active = record.task is not None and not record.task.done()
                record.finalizing = task_active
                if task_active:
                    record.task.cancel()
                record.status = RunStatus.interrupted
                record.updated_at = _now_iso()

        # 在锁外持久化，避免存储调用阻塞其他状态变更。
        if record is not None:
            persisted = await self._persist_status(record, RunStatus.interrupted)
            if not persisted and self._store is not None:
                # ``_persist_status`` 已在内部读取过 existing；此处再次查询存储，检查本地取消与受保护的
                # ``update_status`` 之间记录是否已被其他工作器接管并变为 ``error``。若已接管则返回
                # ``taken_over``，确保客户端看到的状态与存储一致。
                try:
                    existing = await self._store.get(run_id)
                except Exception:
                    existing = None
                if existing is not None and existing.get("status") == "error":
                    # 内存中的 ``record.status`` 仍为 ``interrupted``（上方在锁内设置），而存储行已变为
                    # ``error``。这种短暂不一致不会造成问题：``_persist_status`` 的保护会阻止较晚的
                    # 收尾写入覆盖接管状态，后续读取仍以存储中的权威值为准。
                    logger.info("Run %s local cancel superseded by peer takeover", run_id)
                    return CancelOutcome.taken_over
            logger.info("Run %s cancelled (action=%s)", run_id, action)
            return CancelOutcome.cancelled

        # 非本地运行路径：内存中没有对应记录，必须查询存储。

        if not self.heartbeat_enabled:
            return CancelOutcome.not_active_locally

        if self._store is None:
            return CancelOutcome.unknown

        try:
            row = await self._store.get(run_id)
        except Exception:
            logger.warning("Failed to fetch run %s from store during cancel", run_id, exc_info=True)
            return CancelOutcome.unknown

        if row is None:
            return CancelOutcome.unknown

        store_status = row.get("status")
        if store_status not in ("pending", "running"):
            return CancelOutcome.not_cancellable

        grace_seconds = self.grace_seconds
        lease_expires_at: str | None = row.get("lease_expires_at")

        if not is_lease_expired(lease_expires_at, grace_seconds=grace_seconds):
            return CancelOutcome.lease_valid_elsewhere

        take_over_msg = f"Run reclaimed by worker {self._worker_id}: the owning worker ({row.get('owner_worker_id') or 'unknown'}) stopped renewing its lease and is presumed dead."
        try:
            taken = await self._call_store_with_retry(
                "claim_for_takeover",
                run_id,
                lambda: self._store.claim_for_takeover(
                    run_id,
                    grace_seconds=grace_seconds,
                    error=take_over_msg,
                ),
            )
        except Exception:
            logger.warning("Take-over claim for run %s failed with exception", run_id, exc_info=True)
            return CancelOutcome.unknown

        if taken:
            logger.warning("Run %s taken over by worker %s (action=%s)", run_id, self._worker_id, action)
            return CancelOutcome.taken_over

        # 条件 UPDATE 未匹配到记录，可能有两种原因：
        #   (a) 所有者已续租 → lease_valid_elsewhere。
        #   (b) 查询和接管之间记录已进入终态（运行已完成或已被其他工作器接管）→ not_cancellable 或 taken_over。
        # 重新读取以区分这两种情况。
        try:
            fresh = await self._store.get(run_id)
        except Exception:
            fresh = None
        if fresh is None:
            return CancelOutcome.unknown
        fresh_status = fresh.get("status")
        if fresh_status not in ("pending", "running"):
            if fresh_status == "error":
                logger.info("Run %s takeover lost to another worker already at error", run_id)
                return CancelOutcome.taken_over
            return CancelOutcome.not_cancellable
        # 记录仍处于活动状态，说明所有者已续租。
        return CancelOutcome.lease_valid_elsewhere

    def _compute_lease_expires_at(self) -> str | None:
        '''

        返回：新建运行的租约到期时间，采用 ISO 时间格式。

                单工作器模式关闭心跳时返回 ``None``，使对账流程将崩溃运行视为租约为空的孤儿并立即回收，
                保持引入所有权机制前的行为。多工作器部署启用心跳后才使用租约。
        '''
        if self._run_ownership_config is None:
            return None
        if not self._run_ownership_config.heartbeat_enabled:
            return None
        lease_seconds = self._run_ownership_config.lease_seconds
        return (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()

    async def create_or_reject(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode = DisconnectMode.cancel,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
        model_name: str | None = None,
        user_id: str | None = None,
    ) -> RunRecord:
        '''原子检查线程是否已有运行中任务，并按拒绝、中断或回滚策略决定是否创建新运行。'''
        run_id = str(uuid.uuid4())
        now = _now_iso()

        _supported_strategies = ("reject", "interrupt", "rollback")
        if multitask_strategy not in _supported_strategies:
            raise UnsupportedStrategyError(f"Multitask strategy '{multitask_strategy}' is not yet supported. Supported strategies: {', '.join(_supported_strategies)}")

        lease_expires_at = self._compute_lease_expires_at()
        grace_seconds = self._run_ownership_config.grace_seconds if self._run_ownership_config else 10

        interrupted_records: list[RunRecord] = []
        record = RunRecord(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            status=RunStatus.pending,
            on_disconnect=on_disconnect,
            multitask_strategy=multitask_strategy,
            metadata=metadata or {},
            kwargs=kwargs or {},
            user_id=user_id,
            created_at=now,
            updated_at=now,
            model_name=model_name,
            owner_worker_id=self._worker_id,
            lease_expires_at=lease_expires_at,
        )

        async with self._lock:
            # 1）检查当前工作器中的活动运行；跨工作器冲突由下方存储的部分唯一索引处理。
            local_inflight = [r for r in self._thread_records_locked(thread_id) if r.status in (RunStatus.pending, RunStatus.running) or r.finalizing]

            if multitask_strategy == "reject" and local_inflight:
                raise ConflictError(f"Thread {thread_id} already has an active run")

            if multitask_strategy in ("interrupt", "rollback") and local_inflight:
                logger.info(
                    "Preparing to cancel %d inflight run(s) on thread %s (strategy=%s)",
                    len(local_inflight),
                    thread_id,
                    multitask_strategy,
                )

            # 2）仍在本地锁内时写入存储；跨进程原子性由存储作为事实来源保证。
            if self._store is not None:
                if multitask_strategy == "reject":
                    try:
                        await self._call_store_with_retry(
                            "create_run_atomic",
                            run_id,
                            lambda: self._store.create_run_atomic(
                                run_id=run_id,
                                thread_id=thread_id,
                                owner_worker_id=self._worker_id,
                                lease_expires_at=lease_expires_at,
                                multitask_strategy="reject",
                                assistant_id=assistant_id,
                                user_id=user_id,
                                model_name=model_name,
                                metadata=metadata,
                                kwargs=kwargs,
                                created_at=now,
                                grace_seconds=grace_seconds,
                            ),
                        )
                    except ConflictError:
                        raise
                    except Exception as exc:
                        if _is_unique_violation(exc):
                            raise ConflictError(f"Thread {thread_id} already has an active run") from exc
                        raise
                else:
                    # interrupt / rollback：在同一事务中完成存储端接管和插入。若其他工作器在本次
                    # SELECT FOR UPDATE 与 INSERT 之间抢先操作并触发 IntegrityError，则进行重试。
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            await self._call_store_with_retry(
                                "create_run_atomic",
                                run_id,
                                lambda: self._store.create_run_atomic(
                                    run_id=run_id,
                                    thread_id=thread_id,
                                    owner_worker_id=self._worker_id,
                                    lease_expires_at=lease_expires_at,
                                    multitask_strategy=multitask_strategy,
                                    assistant_id=assistant_id,
                                    user_id=user_id,
                                    model_name=model_name,
                                    metadata=metadata,
                                    kwargs=kwargs,
                                    created_at=now,
                                    grace_seconds=grace_seconds,
                                ),
                            )
                            break
                        except Exception as exc:
                            is_unique = _is_unique_violation(exc)
                            if is_unique and attempt + 1 < max_retries:
                                continue
                            if is_unique:
                                # 唯一键冲突重试次数已用尽；转换为 ConflictError，与 reject 分支一致返回 409
                                # 而非 500。根因相同：另一个工作器抢先创建了此线程的运行。
                                raise ConflictError(f"Thread {thread_id} already has an active run") from exc
                            raise
                    # ``create_run_atomic`` 已在同一事务中把被接管的存储记录标为 interrupted，
                    # 无需再次写入存储。

            # 3）存储插入成功后，才可将记录登记到本地。
            self._runs[run_id] = record
            self._index_run_locked(record)

            # 4）取消本地内存中的活动运行（interrupt / rollback）；对应存储记录已在第 2 步取消。
            if multitask_strategy in ("interrupt", "rollback"):
                for r in local_inflight:
                    if r.finalizing:
                        continue
                    r.abort_action = multitask_strategy
                    r.abort_event.set()
                    task_active = r.task is not None and not r.task.done()
                    r.finalizing = task_active
                    if task_active:
                        r.task.cancel()
                    r.status = RunStatus.interrupted
                    r.updated_at = now
                    interrupted_records.append(r)

        # 在锁外持久化本地取消运行的 interrupted 状态；存储端被接管的记录已完成终态更新。
        for interrupted_record in interrupted_records:
            await self._persist_status(interrupted_record, RunStatus.interrupted)

        logger.info("Run created: run_id=%s thread_id=%s", run_id, thread_id)
        return record

    async def reconcile_orphaned_inflight_runs(
        self,
        *,
        error: str,
        before: str | None = None,
    ) -> list[RunRecord]:
        '''

        将租约过期的持久化活动运行标记为中断并释放所有权。

                In multi-worker deployments (Postgres), a run owned by Worker A that
                still shows ``pending`` / ``running`` after its lease expired means
                Worker A crashed or was partitioned. This worker (B) can safely claim
                and error it out because the lease was not renewed.

                Rows with a still-valid lease are skipped — they belong to another live
                worker. Rows with a NULL lease (pre-ownership data) are reclaimed as
                well, matching the original single-worker recovery behaviour.
        '''
        if self._store is None:
            return []
        grace_seconds = self._run_ownership_config.grace_seconds if self._run_ownership_config else 10
        try:
            rows = await self._call_store_with_retry(
                "list_inflight_with_expired_lease",
                "*",
                lambda: self._store.list_inflight_with_expired_lease(before=before, grace_seconds=grace_seconds),
            )
        except Exception:
            logger.warning("Failed to list orphaned inflight runs for reconciliation", exc_info=True)
            return []

        recovered: list[RunRecord] = []
        now = _now_iso()
        for row in rows:
            try:
                record = self._record_from_store(row)
            except Exception:
                logger.warning("Failed to map orphaned run row during reconciliation", exc_info=True)
                continue

            async with self._lock:
                live_record = self._runs.get(record.run_id)
                if live_record is not None and live_record.status in (RunStatus.pending, RunStatus.running):
                    # 仍由本地任务持有，跳过。
                    continue

            record.status = RunStatus.error
            record.error = error
            record.updated_at = now
            persisted = await self._persist_status(record, RunStatus.error, error=error)
            if not persisted:
                logger.warning("Skipped orphaned run %s recovery because error status was not persisted", record.run_id)
                continue
            recovered.append(record)

        if recovered:
            logger.warning("Recovered %d orphaned inflight run(s) as error", len(recovered))
        return recovered

    async def has_inflight(self, thread_id: str) -> bool:
        '''检查指定线程是否有待执行、运行中或正在收尾的运行记录。'''
        async with self._lock:
            return any(r.status in (RunStatus.pending, RunStatus.running) or r.finalizing for r in self._thread_records_locked(thread_id))

    async def cleanup(self, run_id: str, *, delay: float = 300) -> None:
        '''

        可选等待指定时间后移除运行记录及其索引。'''
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._lock:
            record = self._runs.pop(run_id, None)
            if record is not None:
                self._unindex_run_locked(run_id, record.thread_id)
        logger.debug("Run record %s cleaned up", run_id)


    @property
    def worker_id(self) -> str:
        '''

        返回：this worker's unique identifier.'''
        return self._worker_id

    @property
    def heartbeat_enabled(self) -> bool:
        '''

        返回：``True`` when the heartbeat background task should run.'''
        if self._run_ownership_config is None:
            return False
        return self._run_ownership_config.heartbeat_enabled

    @property
    def grace_seconds(self) -> int:
        '''

        返回：the configured grace seconds.

                All current callers are downstream of ``heartbeat_enabled``, which
                is False whenever ``_run_ownership_config`` is None.  The fallback
                matches the Pydantic model default and is defensive against future
                callers that might reach this property without that guard.
        '''
        return self._run_ownership_config.grace_seconds if self._run_ownership_config else 10

    async def start_heartbeat(self) -> None:
        '''

        启动定期续租和失联运行回收后台任务。

                No-op when ``heartbeat_enabled`` is ``False`` or the task is already running.
        '''
        if not self.heartbeat_enabled:
            return
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_stop = asyncio.Event()
        task = asyncio.create_task(self._heartbeat_loop())
        task.set_name("deerflow-run-lease-heartbeat")
        self._heartbeat_task = task
        logger.info("Run lease heartbeat started for worker %s", self._worker_id)

    async def stop_heartbeat(self) -> None:
        '''

        停止心跳任务并等待其完成。'''
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            try:
                await asyncio.wait_for(self._heartbeat_task, timeout=5.0)
            except TimeoutError:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None
        self._heartbeat_stop = None
        logger.info("Run lease heartbeat stopped for worker %s", self._worker_id)

    async def _heartbeat_loop(self) -> None:
        '''

        周期性续租本进程运行，并检查其他进程遗留的过期租约。

                Lease renewal runs every ``lease_seconds / 3``. Reconciliation
                (sweeping for expired leases owned by dead workers) runs every
                ``lease_seconds`` (every 3rd cycle) so orphaned runs are recovered
                without waiting for a pod restart.

                Both operations are guarded so a transient failure cannot take the
                heartbeat task down — a dead heartbeat means no lease is renewed
                again, and every active run eventually looks orphaned to peers.
        '''
        if self._run_ownership_config is None or self._heartbeat_stop is None:
            return
        lease_seconds = self._run_ownership_config.lease_seconds
        interval = max(1, lease_seconds // 3)
        stop = self._heartbeat_stop
        cycle = 0

        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                break
            except TimeoutError:
                pass

            cycle += 1
            try:
                await self._renew_leases()
            except Exception:
                logger.warning("Heartbeat renewal cycle failed", exc_info=True)

            # 每三个周期（即每个 lease_seconds）执行一次孤儿对账。langgraph_runtime 中的启动对账负责首次扫描；
            # 此周期任务用于发现重启间租约过期的孤儿运行。例如工作器 A 崩溃后，替代工作器可能在租约到期前启动，
            # 启动扫描会跳过仍有效的租约，因此需要周期性再次检查。
            if cycle % 3 == 0:
                try:
                    await self._reconcile_orphans_periodic()
                except Exception:
                    logger.warning("Periodic orphan reconciliation failed", exc_info=True)

    async def _renew_leases(self) -> None:
        '''

        为本进程拥有的活动运行延长数据库租约。'''
        if self._store is None or self._run_ownership_config is None:
            return
        lease_seconds = self._run_ownership_config.lease_seconds
        new_expiry = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()

        async with self._lock:
            # 为当前工作器拥有的 pending/running 运行续租，已完成的后台任务除外。任务尚未创建
            #（``task is None``）的待处理记录仍视为存活：create_run_atomic 插入记录后，工作器启动智能体任务前
            # 存在短暂间隙。若该间隙因事件循环繁忙或检查点加载缓慢而超过 ``lease_seconds``，其他工作器的
            # 对账流程可能把运行当作孤儿回收并标记为 ``error``，即使当前工作器原本仍准备执行它。
            active_runs = [(rid, record) for rid, record in self._runs.items() if record.status in (RunStatus.pending, RunStatus.running) and record.owner_worker_id == self._worker_id and (record.task is None or not record.task.done())]

        for run_id, record in active_runs:
            try:
                updated = await self._call_store_with_retry(
                    "update_lease",
                    run_id,
                    lambda: self._store.update_lease(
                        run_id,
                        owner_worker_id=self._worker_id,
                        lease_expires_at=new_expiry,
                    ),
                )
                if updated:
                    # 此处不加锁更新不会造成问题：该路径只修改 ``lease_expires_at``，而其他并发写入
                    #（``set_status`` / ``_persist_status``）会修改不同字段。重新获取 ``self._lock`` 只会
                    # 与无关的运行变更互相阻塞，没有收益。
                    record.lease_expires_at = new_expiry
                else:
                    # ``update_lease`` 返回 False，表示记录已被其他工作器接管（状态不再是 pending/running，
                    # 或 ``owner_worker_id`` 已变化）。停止本地任务，避免浪费计算资源或在收尾时覆盖接管状态。
                    logger.warning(
                        "Run %s lease renewal failed (status=%s,owner=%s) – worker likely taken over; aborting local task",
                        run_id,
                        record.status.value,
                        record.owner_worker_id,
                    )
                    record.abort_event.set()
                    task_active = record.task is not None and not record.task.done()
                    if task_active:
                        record.task.cancel()
            except Exception:
                logger.warning("Failed to renew lease for run %s", run_id, exc_info=True)

    async def _reconcile_orphans_periodic(self) -> None:
        '''

        扫描租约过期的运行并回收已失联进程的所有权。

                由 ``_heartbeat_loop`` 每隔 ``lease_seconds`` 调用。启动对账负责首次扫描；此周期检查用于发现
                重启间租约过期的孤儿运行。
        '''
        error_msg = "Run lease expired — owning worker is unreachable."
        recovered = await self.reconcile_orphaned_inflight_runs(error=error_msg)
        if recovered:
            logger.warning(
                "Periodic reconciliation recovered %d orphaned run(s) as error",
                len(recovered),
            )

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        '''

        关闭进程时取消所有活动运行，并在限定时间内等待其退出。

                先停止租约心跳，避免续租操作与后续的运行排空过程竞争。

                会话运行由后台 ``asyncio`` 任务执行，并通过共享的检查点保存器写入数据。关闭时会释放检查点
                保存器的资源（例如 Gateway 的 ``AsyncExitStack`` 所持有的 postgres 连接池）。如果此时运行
                仍在执行图，langgraph 的 ``AsyncPregelLoop._checkpointer_put_after_previous`` 可能在连接池
                关闭后进入 ``finally: await checkpointer.aput(...)``。由于
                该写入运行在 langgraph 内部任务中（不在 ``run_agent`` 的调用栈上），因此产生的
                ``psycopg_pool.PoolClosed`` 无法由工作器捕获，会在 ``asyncio.run()`` 关闭阶段作为未处理异常
                抛出（bytedance/deer-flow 问题 #3373）。

                在关闭检查点保存器之前排空正在运行的任务，使能在 ``timeout`` 内结束的运行可趁资源仍开放时
                刷新最终检查点。只有未能自行结束的运行才标记为 ``interrupted``；若运行在排空期间完成
                （例如变为 ``success``），则保留真实终态，而不被统一覆盖。整个排空过程（包括最后的状态持久化）
                都受 ``timeout`` 限制，避免清理卡住或数据库压力导致存储缓慢时工作器无法关闭。这也是防止
                ``app.gateway.app._SHUTDOWN_HOOK_TIMEOUT_SECONDS`` 所保护的信号重入死锁的前提。
                超时后仍活动的运行会被记录，关闭资源时仍可能与其竞争。
        '''
        await self.stop_heartbeat()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        async with self._lock:
            inflight = [record for record in self._runs.values() if record.status in (RunStatus.pending, RunStatus.running) and record.task is not None and not record.task.done()]
            for record in inflight:
                record.abort_action = "interrupt"
                record.abort_event.set()
                record.task.cancel()  # type: ignore[union-attr]  # filtered above
                # 状态应在下方排空事件后确定；若运行在排空期间自行完成，必须保留其真实状态。

        if not inflight:
            return

        tasks = [record.task for record in inflight]
        _, pending = await asyncio.wait(tasks, timeout=timeout)

        # 仅将未自行结束的运行标记并持久化为 ``interrupted``（超时后仍处于 pending，或以取消结束）。
        # 若运行在排空期间正常完成，则保留其自行设置的状态。
        to_persist: list[RunRecord] = []
        async with self._lock:
            for record in inflight:
                task = record.task
                if task not in pending and not task.cancelled():
                    # 运行已自行完成：读取可能抛出的异常，避免出现“异常从未读取”警告，并保留其状态。
                    task.exception()  # type: ignore[union-attr]  # done & not cancelled
                    continue
                if record.status in (RunStatus.pending, RunStatus.running):
                    record.status = RunStatus.interrupted
                    record.updated_at = _now_iso()
                to_persist.append(record)

        # 将最后的状态持久化限制在剩余时间预算内，避免存储缓慢（数据库压力大时
        # ``_call_store_with_retry`` 可能执行退避等待）导致关闭时间超过 ``timeout``。
        if to_persist:
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning("Run drain budget exhausted before persisting %d interrupted run(s) on shutdown", len(to_persist))
            else:
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*(self._persist_status(record, RunStatus.interrupted) for record in to_persist), return_exceptions=True),
                        timeout=remaining,
                    )
                except TimeoutError:
                    logger.warning("Run drain status persistence exceeded the %.1fs budget; %d record(s) may not be persisted", timeout, len(to_persist))
                else:
                    # ``_persist_status`` 会自行捕获并记录错误，并返回 ``False``。检查聚合结果，
                    # 使部分失败能在关闭阶段带上 run_id 显式报告，而不是被 gather 静默吞掉。
                    for record, result in zip(to_persist, results):
                        if isinstance(result, Exception):
                            logger.warning("Unexpected error persisting interrupted status for run %s during shutdown: %r", record.run_id, result)
                        elif result is False:
                            logger.warning("Could not persist interrupted status for run %s during shutdown", record.run_id)

        if pending:
            logger.warning("Run drain exceeded %.1fs on shutdown; %d run task(s) still active and may race checkpointer teardown", timeout, len(pending))
        logger.info("Drained %d in-flight run(s) on shutdown (%d settled within %.1fs)", len(inflight), len(inflight) - len(pending), timeout)


class CancelOutcome(StrEnum):
    '''

    Result of a :meth:`RunManager.cancel` call.'''

    cancelled = "cancelled"
    taken_over = "taken_over"
    lease_valid_elsewhere = "lease_valid_elsewhere"
    not_cancellable = "not_cancellable"
    not_active_locally = "not_active_locally"
    unknown = "unknown"


class ConflictError(Exception):
    '''

    Raised when multitask_strategy=reject and thread has inflight runs.'''


class UnsupportedStrategyError(Exception):
    '''

    Raised when a multitask_strategy value is not yet implemented.'''
