"""提供定时任务轮询、分派及运行结果回调的应用服务。"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException

from deerflow.runtime import ConflictError, RunRecord
from deerflow.scheduler.schedules import next_run_at

logger = logging.getLogger(__name__)


class ScheduledTaskService:
    """协调定时任务的轮询抢占、重叠处理、运行分派与生命周期收尾。"""
    def __init__(
        self,
        *,
        task_repo,
        task_run_repo,
        launch_run,
        poll_interval_seconds: int,
        lease_seconds: int,
        max_concurrent_runs: int,
    ) -> None:
        """初始化仓储、运行分派器以及轮询和租约控制参数。"""
        self._task_repo = task_repo
        self._task_run_repo = task_run_repo
        self._launch_run = launch_run
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_runs = max_concurrent_runs
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def run_once(self, *, now: datetime) -> None:
        """执行一次轮询：在全局并发余量内抢占到期任务并分派运行。"""
        # ``max_concurrent_runs`` 限制的是全部活跃的定时运行，而非单次轮询的抢占批次：
        # 长时间运行会跨多个轮询周期累积，因此每轮只能按剩余并发额度抢占任务。
        active = await self._task_run_repo.count_active_runs()
        budget = self._max_concurrent_runs - active
        if budget <= 0:
            return
        claimed = await self._task_repo.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=budget,
        )
        for task in claimed:
            await self.dispatch_task(task, now=now, trigger="scheduled")

    @staticmethod
    def _is_overlap_conflict(exc: Exception) -> bool:
        """判断异常是否表示同一执行线程已被占用的重叠冲突。"""
        if isinstance(exc, ConflictError):
            return True
        return isinstance(exc, HTTPException) and exc.status_code == 409

    @staticmethod
    def _task_status_for_failure(task: dict[str, Any], *, trigger: str) -> str:
        """根据触发方式和调度类型确定启动失败后任务应保留的状态。"""
        if trigger == "manual":
            # 手动触发失败不能消耗任务未来的调度机会：若一次性任务的 run_at 仍未到达，
            # 否则它会被改为“failed”，从而再也不会被抢占执行。
            return task.get("status") or "enabled"
        if task["schedule_type"] == "once":
            return "failed"
        return "enabled"

    @staticmethod
    def _task_status_for_skip(task: dict[str, Any]) -> str:
        """根据调度类型确定因重叠而跳过后任务应保留的状态。"""
        if task["schedule_type"] == "once":
            # 唯一一次执行已因重叠运行而错过；标为“completed”会错误地表示它执行过。
            return "failed"
        return "enabled"

    async def dispatch_task(
        self,
        task: dict[str, Any],
        *,
        now: datetime,
        trigger: str,
    ) -> dict[str, Any]:
        """创建任务运行记录，处理重叠策略并通过既有运行链路分派任务。"""
        execution_thread_id = task.get("thread_id")
        if task.get("context_mode") == "fresh_thread_per_run" or not execution_thread_id:
            execution_thread_id = str(uuid.uuid4())
        # “skip”也必须适用于每次使用新线程的运行；这类运行不会共享线程，因而下方的
        # 同线程多任务 ConflictError 永远不会触发。必须在创建本次分派的运行记录前检查，
        # 以免该记录把自己计为活跃运行。手动触发遇到活跃运行时会被直接拒绝（路由返回 409），
        # 而不会记录为跳过的执行，因为当时并没有已安排的任务需要发生。
        skip_error: str | None = None
        if task.get("overlap_policy", "skip") == "skip" and await self._task_run_repo.has_active_runs(task["id"]):
            if trigger == "manual":
                return {
                    "outcome": "conflict",
                    "task_run_id": None,
                    "run_id": None,
                    "thread_id": execution_thread_id,
                    "error": "task already has an active run",
                }
            skip_error = "skipped: a previous run of this task is still active"
        task_run_id = f"task-run-{uuid.uuid4().hex}"
        await self._task_run_repo.create(
            run_record_id=task_run_id,
            task_id=task["id"],
            thread_id=execution_thread_id,
            scheduled_for=now,
            trigger=trigger,
            status="queued",
        )
        if skip_error is not None:
            return await self._finalize_skip(task, task_run_id=task_run_id, thread_id=execution_thread_id, now=now, error=skip_error)
        try:
            result = await self._launch_run(
                thread_id=execution_thread_id,
                assistant_id=task.get("assistant_id"),
                prompt=task["prompt"],
                owner_user_id=task.get("user_id"),
                metadata={
                    "scheduled_task_id": task["id"],
                    "scheduled_task_run_id": task_run_id,
                    "scheduled_trigger": trigger,
                },
            )
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            if task["schedule_type"] == "once":
                # 保持“running”直到 handle_run_completion 获得真实终态；启动时即标为
                # “completed”会在运行失败或进程退出后遗留错误状态（启动时由
                # cancel_stuck_once_tasks 负责协调）。
                task_status = "running"
            elif trigger == "manual" and task.get("status") == "paused":
                task_status = "paused"
            else:
                task_status = "enabled"
            await self._task_run_repo.update_status(
                task_run_id,
                status="running",
                run_id=result["run_id"],
                started_at=now,
                # 快速失败的运行可能在本次写入恢复前就到达 handle_run_completion；
                # 绝不能覆盖它已经写入的终态。
                protect_terminal=True,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=result["run_id"],
                last_thread_id=result["thread_id"],
                last_error=None,
                increment_run_count=True,
                # 与上方运行记录写入存在同样的竞争：快速失败运行的完成回调可能已经
                # 终结了一次性任务。
                protect_terminal=True,
            )
            return {
                "outcome": "launched",
                "task_run_id": task_run_id,
                "run_id": result["run_id"],
                "thread_id": result["thread_id"],
                "error": None,
            }
        except Exception as exc:
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            if self._is_overlap_conflict(exc) and trigger == "scheduled" and task.get("overlap_policy", "skip") == "skip":
                return await self._finalize_skip(task, task_run_id=task_run_id, thread_id=execution_thread_id, now=now, error=str(exc))

            task_status = self._task_status_for_failure(task, trigger=trigger)
            await self._task_run_repo.update_status(
                task_run_id,
                status="failed",
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=None,
                last_thread_id=execution_thread_id,
                last_error=str(exc),
                increment_run_count=False,
            )
            return {
                "outcome": "conflict" if self._is_overlap_conflict(exc) else "failed",
                "task_run_id": task_run_id,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": str(exc),
            }

    async def _finalize_skip(
        self,
        task: dict[str, Any],
        *,
        task_run_id: str,
        thread_id: str,
        now: datetime,
        error: str,
    ) -> dict[str, Any]:
        """将因重叠而跳过的运行和关联任务更新为相应状态并返回结果。"""
        next_at = next_run_at(
            task["schedule_type"],
            task["schedule_spec"],
            task["timezone"],
            now=now,
        )
        await self._task_run_repo.update_status(
            task_run_id,
            status="skipped",
            error=error,
            started_at=now,
            finished_at=now,
        )
        await self._task_repo.update_after_launch(
            task["id"],
            status=self._task_status_for_skip(task),
            next_run_at=next_at,
            last_run_at=task.get("last_run_at"),
            last_run_id=task.get("last_run_id"),
            last_thread_id=task.get("last_thread_id"),
            last_error=error if task["schedule_type"] == "once" else None,
            increment_run_count=False,
        )
        return {
            "outcome": "skipped",
            "task_run_id": task_run_id,
            "run_id": None,
            "thread_id": thread_id,
            "error": error,
        }

    async def handle_run_completion(self, record: RunRecord) -> None:
        """接收运行完成回调，写入终态并收尾一次性任务的状态。"""
        metadata = record.metadata or {}
        task_id = metadata.get("scheduled_task_id")
        task_run_id = metadata.get("scheduled_task_run_id")
        user_id = record.user_id
        if not isinstance(task_id, str) or not isinstance(task_run_id, str) or not user_id:
            return

        terminal_status: Literal["success", "failed", "interrupted"] | None
        if record.status.value == "success":
            terminal_status = "success"
            error = None
        elif record.status.value == "interrupted":
            # 与“failed”不同：中断（用户取消或同线程接管）不属于执行失败，
            # 并且不携带失败错误。
            terminal_status = "interrupted"
            error = record.error or "run was interrupted before completion"
        elif record.status.value in {"error", "timeout"}:
            terminal_status = "failed"
            error = record.error
        else:
            terminal_status = None
            error = record.error
        if terminal_status is None:
            return

        await self._task_run_repo.update_status(
            task_run_id,
            status=terminal_status,
            run_id=record.run_id,
            error=error,
            finished_at=datetime.now(UTC),
        )

        task = await self._task_repo.get(task_id, user_id=user_id)
        if task is None:
            return

        updates: dict[str, Any] = {"last_error": error}
        if task["schedule_type"] == "once":
            # 唯一一次执行无论结果如何都已被消耗（运行确已启动，重新启用可能产生重复副作用），
            # 但中断应以“cancelled”结束，而不是“failed”。
            if terminal_status == "success":
                updates["status"] = "completed"
            elif terminal_status == "interrupted":
                updates["status"] = "cancelled"
            else:
                updates["status"] = "failed"
        await self._task_repo.update(task_id, user_id=user_id, updates=updates)

    async def start(self) -> None:
        """清理重启遗留状态后启动后台定时任务轮询循环。"""
        if self._task is not None:
            return
        restart_error = "interrupted: gateway restarted before the run reached a terminal state"
        try:
            stale = await self._task_run_repo.mark_stale_active_runs(error=restart_error)
            if stale:
                logger.warning("Marked %d stale scheduled task run(s) as interrupted after restart", stale)
        except Exception:
            logger.exception("Failed to sweep stale scheduled task runs at startup")
        try:
            # 上方运行记录只是部分状态：已启动的一次性任务会停留在“running”，直到
            # 已失效的完成回调本应将其终结，因此还必须协调其父任务记录。
            stuck = await self._task_repo.cancel_stuck_once_tasks(error=restart_error)
            if stuck:
                logger.warning("Cancelled %d stuck once task(s) after restart", stuck)
        except Exception:
            logger.exception("Failed to reconcile stuck once tasks at startup")
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """发出停止信号并等待后台轮询循环有序结束。"""
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        """持续轮询到期任务；单次轮询失败时记录异常并在下个周期重试。"""
        while not self._stop.is_set():
            try:
                await self.run_once(now=datetime.now(UTC))
            except Exception:
                # 瞬时数据库错误（例如 SQLite“database is locked”）不能使轮询任务
                # 在进程剩余生命周期内停止。
                logger.exception("Scheduled task poll failed; retrying next interval")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue
