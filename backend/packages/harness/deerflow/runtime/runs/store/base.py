'定义 base 模块提供的职责与可复用接口。\n\nAbstract interface for run metadata storage.\n\nRunManager depends on this interface. Implementations:\n- MemoryRunStore: in-memory dict (development, tests)\n- Future: RunRepository backed by SQLAlchemy ORM\n\nAll methods accept an optional user_id for user isolation.\nWhen user_id is None, no user filtering is applied (single-user mode).\n'

from __future__ import annotations

import abc
from typing import Any


class RunStore(abc.ABC):
    '封装 RunStore 的状态、协作关系与公开操作'
    @abc.abstractmethod
    async def put(
        self,
        run_id: str,
        *,
        thread_id: str,
        assistant_id: str | None = None,
        user_id: str | None = None,
        model_name: str | None = None,
        status: str = "pending",
        multitask_strategy: str = "reject",
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
        created_at: str | None = None,
        owner_worker_id: str | None = None,
        lease_expires_at: str | None = None,
    ) -> None:
        '执行 put 的明确职责，并返回与调用约定一致的结果'
        pass

    @abc.abstractmethod
    async def get(
        self,
        run_id: str,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        '读取并返回，并遵守 get 所表达的接口约束'
        pass

    @abc.abstractmethod
    async def list_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        '收集并返回，并遵守 list_by_thread 所表达的接口约束'
        pass

    async def list_successful_regenerate_sources(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> set[str]:
        '收集并返回，并遵守 list_successful_regenerate_sources 所表达的接口约束。\n\nReturn source run IDs superseded by successful regenerations.\n\n        Implementations must inspect the complete thread and must not apply the\n        normal bounded run-list limit.\n        '
        raise NotImplementedError

    async def get_many_by_thread(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        '读取并返回，并遵守 get_many_by_thread 所表达的接口约束。\n\nBatch-load selected runs belonging to one thread.'
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
        stop_reason: str | None = None,
    ) -> bool | None:
        '更新目标状态并返回最新结果，并遵守 update_status 所表达的接口约束。\n\nUpdate a run status.\n\n        Returns ``False`` when the store can prove no row was updated. Older or\n        lightweight stores may return ``None`` when they cannot report rowcount.\n        '
        pass

    @abc.abstractmethod
    async def delete(self, run_id: str) -> None:
        '删除目标资源并返回操作结果，并遵守 delete 所表达的接口约束'
        pass

    @abc.abstractmethod
    async def update_model_name(
        self,
        run_id: str,
        model_name: str | None,
    ) -> None:
        '更新目标状态并返回最新结果，并遵守 update_model_name 所表达的接口约束。\n\nUpdate the model_name field for an existing run.'
        pass

    @abc.abstractmethod
    async def update_run_completion(
        self,
        run_id: str,
        *,
        status: str,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_tokens: int = 0,
        llm_call_count: int = 0,
        lead_agent_tokens: int = 0,
        subagent_tokens: int = 0,
        middleware_tokens: int = 0,
        token_usage_by_model: dict[str, dict[str, int]] | None = None,
        message_count: int = 0,
        last_ai_message: str | None = None,
        first_human_message: str | None = None,
        error: str | None = None,
    ) -> bool | None:
        '更新目标状态并返回最新结果，并遵守 update_run_completion 所表达的接口约束。\n\nPersist final completion fields.\n\n        Returns ``False`` when the store can prove no row was updated.\n        '
        pass

    async def update_run_progress(
        self,
        run_id: str,
        *,
        total_input_tokens: int | None = None,
        total_output_tokens: int | None = None,
        total_tokens: int | None = None,
        llm_call_count: int | None = None,
        lead_agent_tokens: int | None = None,
        subagent_tokens: int | None = None,
        middleware_tokens: int | None = None,
        token_usage_by_model: dict[str, dict[str, int]] | None = None,
        message_count: int | None = None,
        last_ai_message: str | None = None,
        first_human_message: str | None = None,
    ) -> None:
        '更新目标状态并返回最新结果，并遵守 update_run_progress 所表达的接口约束。\n\nPersist a best-effort running snapshot without changing run status.'
        return None

    @abc.abstractmethod
    async def list_pending(self, *, before: str | None = None) -> list[dict[str, Any]]:
        '收集并返回，并遵守 list_pending 所表达的接口约束'
        pass

    @abc.abstractmethod
    async def list_inflight(self, *, before: str | None = None) -> list[dict[str, Any]]:
        '收集并返回，并遵守 list_inflight 所表达的接口约束。\n\nReturn persisted runs that are still ``pending`` or ``running``.'
        pass

    @abc.abstractmethod
    async def aggregate_tokens_by_thread(self, thread_id: str, *, include_active: bool = False) -> dict[str, Any]:
        '执行 aggregate_tokens_by_thread 的明确职责，并返回与调用约定一致的结果。\n\nAggregate token usage for completed runs in a thread.\n\n        Returns a dict with keys: total_tokens, total_input_tokens,\n        total_output_tokens, total_runs, by_model (model_name → {tokens, runs}),\n        by_caller ({lead_agent, subagent, middleware}).\n        '
        pass

    @abc.abstractmethod
    async def update_lease(
        self,
        run_id: str,
        *,
        owner_worker_id: str,
        lease_expires_at: str,
    ) -> bool:
        '更新目标状态并返回最新结果，并遵守 update_lease 所表达的接口约束。\n\nRenew the lease on an active run. Returns ``False`` when no row matched.'
        pass

    @abc.abstractmethod
    async def claim_for_takeover(
        self,
        run_id: str,
        *,
        grace_seconds: int,
        error: str,
    ) -> bool:
        "执行 claim_for_takeover 的明确职责，并返回与调用约定一致的结果。\n\nAtomically mark an expired-lease active run as ``error``.\n\n        Only rows whose lease has expired past *grace_seconds* (or whose\n        lease is NULL — pre-ownership data) are updated.  The conditional\n        WHERE closes the race between the caller's stale read of the lease\n        and a concurrent heartbeat renewal by the owning worker.\n\n        Returns ``False`` when:\n          - the run is no longer ``pending`` / ``running``,\n          - the lease is still valid (owner heartbeat is alive), or\n          - the row doesn't exist.\n        "
        pass

    @abc.abstractmethod
    async def list_inflight_with_expired_lease(
        self,
        *,
        before: str | None = None,
        grace_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        '收集并返回，并遵守 list_inflight_with_expired_lease 所表达的接口约束。\n\nReturn active runs whose lease has expired (or is NULL for pre-ownership rows).'
        pass

    @abc.abstractmethod
    async def create_run_atomic(
        self,
        run_id: str,
        *,
        thread_id: str,
        owner_worker_id: str,
        lease_expires_at: str | None,
        multitask_strategy: str = "reject",
        assistant_id: str | None = None,
        user_id: str | None = None,
        model_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        created_at: str | None = None,
        grace_seconds: int = 10,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        '创建并返回，并遵守 create_run_atomic 所表达的接口约束。\n\nAtomically create a run row with cross-process thread-uniqueness.\n\n        Returns ``(new_run_dict, claimed_run_dicts)``.\n        Raises ``IntegrityError`` on conflict for ``reject`` strategy.\n        '
        pass
