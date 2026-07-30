'定义 memory 模块提供的职责与可复用接口。\n\nIn-memory RunStore. Used when database.backend=memory (default) and in tests.\n\nEquivalent to the original RunManager._runs dict behavior.\n'

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.runtime.runs.store.base import RunStore


class MemoryRunStore(RunStore):
    '封装 MemoryRunStore 的状态、协作关系与公开操作'
    def __init__(self) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        self._runs: dict[str, dict[str, Any]] = {}
        # Secondary index: thread_id -> insertion-ordered run_id set (a dict is
        # used as an ordered set), maintained in lockstep with ``_runs`` so
        # per-thread queries avoid O(total in-memory runs) full scans. Mirrors
        # the index ``RunManager`` keeps over its own in-memory records.
        self._runs_by_thread: dict[str, dict[str, None]] = {}

    def _index_run(self, run_id: str, thread_id: str) -> None:
        '执行 _index_run 的明确职责，并返回与调用约定一致的结果。\n\nRegister *run_id* under *thread_id* in the secondary index.'
        self._runs_by_thread.setdefault(thread_id, {})[run_id] = None

    def _unindex_run(self, run_id: str, thread_id: str) -> None:
        '执行 _unindex_run 的明确职责，并返回与调用约定一致的结果。\n\nDrop *run_id* from the *thread_id* bucket, removing the bucket when empty.'
        bucket = self._runs_by_thread.get(thread_id)
        if bucket is not None:
            bucket.pop(run_id, None)
            if not bucket:
                self._runs_by_thread.pop(thread_id, None)

    async def put(
        self,
        run_id,
        *,
        thread_id,
        assistant_id=None,
        user_id=None,
        model_name=None,
        status="pending",
        multitask_strategy="reject",
        metadata=None,
        kwargs=None,
        error=None,
        stop_reason=None,
        created_at=None,
        owner_worker_id=None,
        lease_expires_at=None,
    ):
        '执行 put 的明确职责，并返回与调用约定一致的结果'
        now = datetime.now(UTC).isoformat()
        self._runs[run_id] = {
            "run_id": run_id,
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "user_id": user_id,
            "model_name": model_name,
            "status": status,
            "multitask_strategy": multitask_strategy,
            "metadata": metadata or {},
            "kwargs": kwargs or {},
            "error": error,
            "stop_reason": stop_reason,
            "created_at": created_at or now,
            "updated_at": now,
            "owner_worker_id": owner_worker_id,
            "lease_expires_at": lease_expires_at,
        }
        self._index_run(run_id, thread_id)

    async def get(self, run_id, *, user_id=None):
        '读取并返回，并遵守 get 所表达的接口约束'
        run = self._runs.get(run_id)
        if run is None:
            return None
        if user_id is not None and run.get("user_id") != user_id:
            return None
        return run

    async def list_by_thread(self, thread_id, *, user_id=None, limit=100):
        # Use the thread index for an O(runs-in-thread) lookup instead of
        # scanning every run. ``self._runs.get`` is defense-in-depth: it drops a
        # stale id still in the index but already gone from ``_runs``.
        '收集并返回，并遵守 list_by_thread 所表达的接口约束'
        run_ids = self._runs_by_thread.get(thread_id)
        if not run_ids:
            return []
        results = [run for run_id in run_ids if (run := self._runs.get(run_id)) is not None and (user_id is None or run.get("user_id") == user_id)]
        results.sort(key=lambda r: r["created_at"], reverse=True)
        return results[:limit]

    async def list_successful_regenerate_sources(self, thread_id, *, user_id=None):
        '收集并返回，并遵守 list_successful_regenerate_sources 所表达的接口约束'
        run_ids = self._runs_by_thread.get(thread_id) or ()
        sources: set[str] = set()
        for run_id in run_ids:
            run = self._runs.get(run_id)
            if run is None or run.get("status") != "success":
                continue
            if user_id is not None and run.get("user_id") != user_id:
                continue
            source = (run.get("metadata") or {}).get("regenerate_from_run_id")
            if isinstance(source, str) and source:
                sources.add(source)
        return sources

    async def get_many_by_thread(self, thread_id, run_ids, *, user_id=None):
        '读取并返回，并遵守 get_many_by_thread 所表达的接口约束'
        thread_run_ids = self._runs_by_thread.get(thread_id) or ()
        return {run_id: run for run_id in thread_run_ids if run_id in run_ids and (run := self._runs.get(run_id)) is not None and (user_id is None or run.get("user_id") == user_id)}

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        '更新目标状态并返回最新结果，并遵守 update_status 所表达的接口约束'
        run = self._runs.get(run_id)
        if run is None:
            return False
        # Guard: only transition rows that are still active. ``interrupted``
        # is included for the rollback path (``interrupted → error`` finalize).
        if run["status"] not in ("pending", "running", "interrupted"):
            return False
        run["status"] = status
        if error is not None:
            run["error"] = error
        if stop_reason is not None:
            run["stop_reason"] = stop_reason
        run["updated_at"] = datetime.now(UTC).isoformat()
        return True

    async def update_model_name(self, run_id, model_name):
        '更新目标状态并返回最新结果，并遵守 update_model_name 所表达的接口约束'
        if run_id in self._runs:
            self._runs[run_id]["model_name"] = model_name
            self._runs[run_id]["updated_at"] = datetime.now(UTC).isoformat()

    async def delete(self, run_id):
        '删除目标资源并返回操作结果，并遵守 delete 所表达的接口约束'
        run = self._runs.pop(run_id, None)
        if run is not None:
            self._unindex_run(run_id, run["thread_id"])

    async def update_run_completion(self, run_id, *, status, **kwargs):
        '更新目标状态并返回最新结果，并遵守 update_run_completion 所表达的接口约束'
        if run_id in self._runs:
            self._runs[run_id]["status"] = status
            for key, value in kwargs.items():
                if value is not None:
                    self._runs[run_id][key] = value
            self._runs[run_id]["updated_at"] = datetime.now(UTC).isoformat()
            return True
        return False

    async def update_run_progress(self, run_id, **kwargs):
        '更新目标状态并返回最新结果，并遵守 update_run_progress 所表达的接口约束'
        if run_id in self._runs and self._runs[run_id].get("status") == "running":
            for key, value in kwargs.items():
                if value is not None:
                    self._runs[run_id][key] = value
            self._runs[run_id]["updated_at"] = datetime.now(UTC).isoformat()

    async def list_pending(self, *, before=None):
        '收集并返回，并遵守 list_pending 所表达的接口约束'
        now = before or datetime.now(UTC).isoformat()
        results = [r for r in self._runs.values() if r["status"] == "pending" and r["created_at"] <= now]
        results.sort(key=lambda r: r["created_at"])
        return results

    async def list_inflight(self, *, before=None):
        '收集并返回，并遵守 list_inflight 所表达的接口约束'
        now = before or datetime.now(UTC).isoformat()
        results = [r for r in self._runs.values() if r["status"] in ("pending", "running") and r["created_at"] <= now]
        results.sort(key=lambda r: r["created_at"])
        return results

    async def aggregate_tokens_by_thread(self, thread_id: str, *, include_active: bool = False) -> dict[str, Any]:
        '执行 aggregate_tokens_by_thread 的明确职责，并返回与调用约定一致的结果'
        statuses = ("success", "error", "running") if include_active else ("success", "error")
        # Use the thread index for an O(runs-in-thread) lookup instead of
        # scanning every run in the process (mirrors ``list_by_thread``).
        run_ids = self._runs_by_thread.get(thread_id) or ()
        completed = [run for run_id in run_ids if (run := self._runs.get(run_id)) is not None and run.get("status") in statuses]
        by_model: dict[str, dict] = {}
        for r in completed:
            usage_by_model = r.get("token_usage_by_model") or {}
            if usage_by_model:
                for model, usage in usage_by_model.items():
                    entry = by_model.setdefault(model, {"tokens": 0, "runs": 0})
                    entry["tokens"] += usage.get("total_tokens", 0)
                    entry["runs"] += 1
            else:
                # Fallback for rows written before per-model accounting landed:
                # attribute the whole run to its single ``model_name``. Keeps
                # the legacy lead-only behavior for old data instead of
                # silently dropping it.
                model = r.get("model_name") or "unknown"
                entry = by_model.setdefault(model, {"tokens": 0, "runs": 0})
                entry["tokens"] += r.get("total_tokens", 0)
                entry["runs"] += 1
        return {
            "total_tokens": sum(r.get("total_tokens", 0) for r in completed),
            "total_input_tokens": sum(r.get("total_input_tokens", 0) for r in completed),
            "total_output_tokens": sum(r.get("total_output_tokens", 0) for r in completed),
            "total_runs": len(completed),
            "by_model": by_model,
            "by_caller": {
                "lead_agent": sum(r.get("lead_agent_tokens", 0) for r in completed),
                "subagent": sum(r.get("subagent_tokens", 0) for r in completed),
                "middleware": sum(r.get("middleware_tokens", 0) for r in completed),
            },
        }

    # ------------------------------------------------------------------
    # Multi-worker run ownership methods
    # ------------------------------------------------------------------

    async def update_lease(
        self,
        run_id: str,
        *,
        owner_worker_id: str,
        lease_expires_at: str,
    ) -> bool:
        '更新目标状态并返回最新结果，并遵守 update_lease 所表达的接口约束'
        run = self._runs.get(run_id)
        if run is None:
            return False
        if run["status"] not in ("pending", "running"):
            return False
        if run.get("owner_worker_id") != owner_worker_id:
            return False
        run["owner_worker_id"] = owner_worker_id
        run["lease_expires_at"] = lease_expires_at
        run["updated_at"] = datetime.now(UTC).isoformat()
        return True

    async def claim_for_takeover(
        self,
        run_id: str,
        *,
        grace_seconds: int,
        error: str,
    ) -> bool:
        '执行 claim_for_takeover 的明确职责，并返回与调用约定一致的结果'
        from deerflow.utils.time import is_lease_expired

        run = self._runs.get(run_id)
        if run is None:
            return False
        if run["status"] not in ("pending", "running"):
            return False
        lease = run.get("lease_expires_at")
        if not is_lease_expired(lease, grace_seconds=grace_seconds):
            return False
        run["status"] = "error"
        run["error"] = error
        run["updated_at"] = datetime.now(UTC).isoformat()
        return True

    async def list_inflight_with_expired_lease(
        self,
        *,
        before: str | None = None,
        grace_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        '收集并返回，并遵守 list_inflight_with_expired_lease 所表达的接口约束'
        now_dt = datetime.fromisoformat(before) if before else datetime.now(UTC)
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
        results = []
        for r in self._runs.values():
            if r["status"] not in ("pending", "running"):
                continue
            created_at = r.get("created_at", "")
            if not created_at:
                continue
            try:
                created_dt = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                continue
            if created_dt > now_dt:
                continue
            lease = r.get("lease_expires_at")
            if lease is None:
                # Pre-ownership rows: no lease means orphaned
                results.append(r)
            else:
                try:
                    lease_dt = datetime.fromisoformat(lease)
                    # Treat naive values as UTC — same convention as
                    # ``coerce_iso`` in the SQL store, so the comparison
                    # against the aware ``cutoff`` does not raise
                    # ``TypeError`` when heartbeat is enabled on SQLite
                    # (which drops tzinfo on read).
                    if lease_dt.tzinfo is None:
                        lease_dt = lease_dt.replace(tzinfo=UTC)
                    if lease_dt < cutoff:
                        results.append(r)
                except (ValueError, TypeError):
                    results.append(r)
        results.sort(key=lambda r: r["created_at"])
        return results

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
        '创建并返回，并遵守 create_run_atomic 所表达的接口约束'
        from deerflow.runtime.runs.manager import ConflictError

        now = datetime.now(UTC).isoformat()
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)

        # For reject: check if any active run exists
        if multitask_strategy == "reject":
            for r in self._runs.values():
                if r["thread_id"] == thread_id and r["status"] in ("pending", "running"):
                    raise ConflictError(f"Thread {thread_id} already has an active run")

        # For interrupt/rollback: claim inflight runs.
        # Two-pass so the memory path mirrors the SQL store's transactional
        # semantics — if any candidate is a live run owned by another worker
        # we must raise ConflictError WITHOUT having already mutated earlier
        # candidates. Mutating inline would leave the store in a half-
        # interrupted state on raise, diverging from SQL where a raise rolls
        # the whole transaction back.
        claimed = []
        if multitask_strategy in ("interrupt", "rollback"):
            candidates: list[dict[str, Any]] = []
            for r in self._runs.values():
                if r["thread_id"] != thread_id:
                    continue
                if r["status"] not in ("pending", "running"):
                    continue
                existing_lease = r.get("lease_expires_at")
                if existing_lease is not None:
                    try:
                        lease_dt = datetime.fromisoformat(existing_lease)
                        # Treat naive values as UTC — same convention as
                        # the SQL store and ``coerce_iso``, so the
                        # comparison against the aware ``cutoff`` does not
                        # raise ``TypeError``.
                        if lease_dt.tzinfo is None:
                            lease_dt = lease_dt.replace(tzinfo=UTC)
                        if lease_dt >= cutoff and r.get("owner_worker_id") != owner_worker_id:
                            # Live run owned by another worker — cannot
                            # interrupt, and the partial unique index would
                            # reject the INSERT anyway. Surface as ConflictError
                            # so the caller gets a clean signal. Raise before
                            # any mutation so the store is left untouched.
                            raise ConflictError(f"Thread {thread_id} already has an active run owned by another worker")
                    except (ValueError, TypeError):
                        pass
                candidates.append(r)
            for r in candidates:
                r["status"] = "interrupted"
                r["error"] = "Cancelled by newer run"
                r["owner_worker_id"] = owner_worker_id
                r["updated_at"] = now
                claimed.append(r)

        new_row = {
            "run_id": run_id,
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "user_id": user_id,
            "model_name": model_name,
            "status": "pending",
            "multitask_strategy": multitask_strategy,
            "metadata": metadata or {},
            "kwargs": kwargs or {},
            "error": None,
            "owner_worker_id": owner_worker_id,
            "lease_expires_at": lease_expires_at,
            "created_at": created_at or now,
            "updated_at": now,
        }
        self._runs[run_id] = new_row
        self._index_run(run_id, thread_id)
        return new_row, claimed
