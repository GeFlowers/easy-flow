'''

定义运行元数据仓储的接口，供运行管理器和 PostgreSQL 实现共享。方法支持按用户隔离记录；
显式传入 ``None`` 表示不追加用户筛选。
'''

from __future__ import annotations

import abc
from typing import Any


class RunStore(abc.ABC):

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
        '''插入或覆盖运行记录及其可恢复元数据。'''
        pass

    @abc.abstractmethod
    async def get(
        self,
        run_id: str,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        '''按运行 ID 查询记录，并可选限制用户归属。'''
        pass

    @abc.abstractmethod
    async def list_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        '''查询指定线程的运行历史，并应用用户范围和数量限制。'''
        pass

    async def list_successful_regenerate_sources(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> set[str]:
        '''返回已被成功重新生成操作替代的源运行 ID，不截断线程历史。'''
        raise NotImplementedError

    async def get_many_by_thread(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        '''批量读取指定线程中的运行记录，并以运行 ID 为键返回。'''
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
        '''更新运行状态和可选错误信息；确认没有匹配记录时返回 ``False``。'''
        pass

    @abc.abstractmethod
    async def delete(self, run_id: str) -> None:
        '''删除指定运行记录及其关联数据。'''
        pass

    @abc.abstractmethod
    async def update_model_name(
        self,
        run_id: str,
        model_name: str | None,
    ) -> None:
        '''更新已有运行所使用的模型名称。'''
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
        '''保存运行终态、Token 统计、消息摘要和错误信息。'''
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
        '''更新运行过程中的统计快照，不改变当前状态；实现可忽略此写入。'''
        return None

    @abc.abstractmethod
    async def list_pending(self, *, before: str | None = None) -> list[dict[str, Any]]:
        '''列出创建时间早于指定时刻的待处理运行。'''
        pass

    @abc.abstractmethod
    async def list_inflight(self, *, before: str | None = None) -> list[dict[str, Any]]:
        '''列出仍处于待处理或执行状态的持久化运行。'''
        pass

    @abc.abstractmethod
    async def aggregate_tokens_by_thread(self, thread_id: str, *, include_active: bool = False) -> dict[str, Any]:
        '''汇总线程运行的 Token 用量，并按模型和调用来源拆分。'''
        pass

    @abc.abstractmethod
    async def update_lease(
        self,
        run_id: str,
        *,
        owner_worker_id: str,
        lease_expires_at: str,
    ) -> bool:
        '''延长活跃运行的工作进程租约；记录不存在或已结束时返回 ``False``。'''
        pass

    @abc.abstractmethod
    async def claim_for_takeover(
        self,
        run_id: str,
        *,
        grace_seconds: int,
        error: str,
    ) -> bool:
        '''原子接管超过宽限期的运行并标记失败，避免覆盖并发续租的活动任务。'''
        pass

    @abc.abstractmethod
    async def list_inflight_with_expired_lease(
        self,
        *,
        before: str | None = None,
        grace_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        '''列出租约过期或尚无租约的活跃运行，供启动恢复流程处理。'''
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
        '''原子创建运行并执行同线程并发策略，返回新记录及被接管的旧记录。'''
        pass
