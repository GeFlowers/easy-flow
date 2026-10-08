'''

逐行 JSON 文件形式的 RunEventStore 实现。

每个运行的事件保存在单独文件中：
``.deer-flow/threads/{thread_id}/runs/{run_id}.jsonl``

所有类别（message、trace、lifecycle）保存在同一文件中。
此后端适用于轻量级单节点部署。

**仅保证单进程使用**：内存 seq 计数器属于当前进程。
共享目录的多进程部署会产生重复或非单调的 seq 值。
多进程或高并发部署应使用 ``DbRunEventStore``。

文件读写通过 ``asyncio.to_thread`` 转移到线程池，避免阻塞事件循环。
每个会话线程使用独立 ``asyncio.Lock``，在单进程内串行写入，防止记录行交错。

已知取舍：``list_messages()`` 必须扫描线程的全部运行文件，以便将不同运行的
消息统一按 seq 排序；``list_events()`` 只读取单个文件，开销较小。
'''

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.user_context import AUTO, _AutoSentinel

logger = logging.getLogger(__name__)

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


class JsonlRunEventStore(RunEventStore):

    def __init__(self, base_dir: str | Path | None = None):
        '''初始化 JSONL 存储根目录及进程内序号、写锁缓存。'''
        self._base_dir = Path(base_dir) if base_dir else Path(".deer-flow")
        self._seq_counters: dict[str, int] = {}
        self._write_locks: dict[str, asyncio.Lock] = {}

    def _get_write_lock(self, thread_id: str) -> asyncio.Lock:
        '''获取该线程专用的异步写锁，避免同进程记录行交错。'''
        return self._write_locks.setdefault(thread_id, asyncio.Lock())

    @staticmethod
    def _validate_id(value: str, label: str) -> str:
        '''

        校验标识是否可安全用于文件系统路径。'''
        if not value or not _SAFE_ID_PATTERN.match(value):
            raise ValueError(f"Invalid {label}: must be alphanumeric/dash/underscore, got {value!r}")
        return value

    def _thread_dir(self, thread_id: str) -> Path:
        '''校验线程 ID 并返回其运行事件目录。'''
        self._validate_id(thread_id, "thread_id")
        return self._base_dir / "threads" / thread_id / "runs"

    def _run_file(self, thread_id: str, run_id: str) -> Path:
        '''校验运行 ID 并返回对应事件文件路径。'''
        self._validate_id(run_id, "run_id")
        return self._thread_dir(thread_id) / f"{run_id}.jsonl"

    def _next_seq(self, thread_id: str) -> int:
        '''为线程内新事件分配并缓存下一个递增序号。'''
        self._seq_counters[thread_id] = self._seq_counters.get(thread_id, 0) + 1
        return self._seq_counters[thread_id]

    def _compute_max_seq(self, thread_id: str) -> int:
        '''

        扫描线程的全部运行文件并计算最大序号；本方法执行阻塞文件读写。'''
        max_seq = 0
        thread_dir = self._thread_dir(thread_id)
        if thread_dir.exists():
            for f in thread_dir.glob("*.jsonl"):
                for line in f.read_text(encoding="utf-8").strip().splitlines():
                    try:
                        record = json.loads(line)
                        max_seq = max(max_seq, record.get("seq", 0))
                    except json.JSONDecodeError:
                        logger.debug("Skipping malformed JSONL line in %s", f)
        return max_seq

    async def _ensure_seq_loaded(self, thread_id: str) -> None:
        '''

        将现有文件中的最大 seq 加载到内存计数器，避免阻塞事件循环。'''
        if thread_id in self._seq_counters:
            return
        max_seq = await asyncio.to_thread(self._compute_max_seq, thread_id)
        self._seq_counters[thread_id] = max_seq

    def _write_record(self, record: dict) -> None:
        '''将单条事件以 JSON 行追加到对应运行文件。'''
        path = self._run_file(record["thread_id"], record["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")

    def _read_thread_events(self, thread_id: str) -> list[dict]:
        '''

        读取线程全部事件并按 seq 排序；本方法执行阻塞文件读写。'''
        events = []
        thread_dir = self._thread_dir(thread_id)
        if not thread_dir.exists():
            return events
        for f in sorted(thread_dir.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").strip().splitlines():
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug("Skipping malformed JSONL line in %s", f)
        events.sort(key=lambda e: e.get("seq", 0))
        return events

    def _read_run_events(self, thread_id: str, run_id: str) -> list[dict]:
        '''

        读取指定运行文件中的事件；本方法执行阻塞文件读写。'''
        path = self._run_file(thread_id, run_id)
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping malformed JSONL line in %s", path)
        events.sort(key=lambda e: e.get("seq", 0))
        return events

    def _delete_thread_files(self, thread_id: str) -> None:
        '''删除线程目录下所有运行事件文件。'''
        thread_dir = self._thread_dir(thread_id)
        if thread_dir.exists():
            for f in thread_dir.glob("*.jsonl"):
                f.unlink()

    def _delete_run_file(self, thread_id: str, run_id: str) -> None:
        '''删除指定运行的 JSONL 事件文件（若存在）。'''
        path = self._run_file(thread_id, run_id)
        if path.exists():
            path.unlink()

    async def put(self, *, thread_id, run_id, event_type, category, content="", metadata=None, created_at=None):
        '''为单条事件分配线程序号并异步追加到 JSONL 文件。'''
        async with self._get_write_lock(thread_id):
            await self._ensure_seq_loaded(thread_id)
            seq = self._next_seq(thread_id)
            record = {
                "thread_id": thread_id,
                "run_id": run_id,
                "event_type": event_type,
                "category": category,
                "content": content,
                "metadata": metadata or {},
                "seq": seq,
                "created_at": created_at or datetime.now(UTC).isoformat(),
            }
            await asyncio.to_thread(self._write_record, record)
            return record

    async def put_batch(self, events):
        '''

        在每个线程的写锁内持久化一批事件。

                在同一个线程写锁内分配整批 seq，并通过一次文件写入追加全部记录，
                减少逐条写入中途失败留下部分记录、重试后重复保存的风险。
                调用方（例如 worker.py 的刷新重试路径）会在失败时重新缓存整批事件。
        '''
        if not events:
            return []

        by_thread: dict[str, list[dict[str, Any]]] = {}
        for ev in events:
            by_thread.setdefault(ev["thread_id"], []).append(ev)

        results: list[dict[str, Any]] = []
        for thread_id, batch in by_thread.items():
            records = await self._write_batch_async(thread_id, batch)
            results.extend(records)
        return results

    async def _write_batch_async(self, thread_id: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        '''在同一线程锁内构造连续序号记录，并一次性追加整个批次。'''
        async with self._get_write_lock(thread_id):
            await self._ensure_seq_loaded(thread_id)
            records: list[dict[str, Any]] = []
            for ev in batch:
                seq = self._next_seq(thread_id)
                record = {
                    "thread_id": thread_id,
                    "run_id": ev["run_id"],
                    "event_type": ev["event_type"],
                    "category": ev["category"],
                    "content": ev.get("content", ""),
                    "metadata": ev.get("metadata") or {},
                    "seq": seq,
                    "created_at": ev.get("created_at") or datetime.now(UTC).isoformat(),
                }
                records.append(record)
            path = self._run_file(thread_id, batch[0]["run_id"])
            await asyncio.to_thread(self._append_records, path, records)
            return records

    def _append_records(self, path: Path, records: list[dict[str, Any]]) -> None:
        '''将一组记录序列化为 JSON 行并通过一次文件写入追加。'''
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(json.dumps(r, default=str, ensure_ascii=False) + "\n" for r in records)
        with open(path, "a", encoding="utf-8") as f:
            f.write(lines)

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None, user_id: str | None | _AutoSentinel = AUTO):
        '''扫描线程事件并按序号游标返回最近或后续消息页。'''
        all_events = await asyncio.to_thread(self._read_thread_events, thread_id)
        messages = [e for e in all_events if e.get("category") == "message"]

        if before_seq is not None:
            messages = [e for e in messages if e["seq"] < before_seq]
            return messages[-limit:]
        elif after_seq is not None:
            messages = [e for e in messages if e["seq"] > after_seq]
            return messages[:limit]
        else:
            return messages[-limit:]

    async def list_events(self, thread_id, run_id, *, event_types=None, task_id=None, limit=500, after_seq=None):
        '''读取指定运行的事件文件，并应用类型、子任务及游标筛选。'''
        events = await asyncio.to_thread(self._read_run_events, thread_id, run_id)
        if event_types is not None:
            events = [e for e in events if e.get("event_type") in event_types]
        if task_id is not None:
            events = [e for e in events if (e.get("metadata") or {}).get("task_id") == task_id]
        if after_seq is not None:
            events = [e for e in events if e.get("seq", 0) > after_seq]
        return events[:limit]

    async def list_messages_by_run(self, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None):
        '''从单个运行文件分页读取消息记录。'''
        events = await asyncio.to_thread(self._read_run_events, thread_id, run_id)
        filtered = [e for e in events if e.get("category") == "message"]
        if before_seq is not None:
            filtered = [e for e in filtered if e.get("seq", 0) < before_seq]
        if after_seq is not None:
            filtered = [e for e in filtered if e.get("seq", 0) > after_seq]
        if after_seq is not None:
            return filtered[:limit]
        else:
            return filtered[-limit:] if len(filtered) > limit else filtered

    async def get_last_visible_ai_seq_by_run(self, thread_id, run_ids, *, user_id: str | None | _AutoSentinel = AUTO):
        '''为每个运行扫描最近的非中间件助手回复并返回其序号。'''

        def _scan() -> dict[str, int]:
            '''在线程池中读取文件并计算每个运行最后一条可见回复。'''
            result: dict[str, int] = {}
            for run_id in run_ids:
                for event in reversed(self._read_run_events(thread_id, run_id)):
                    caller = str((event.get("metadata") or {}).get("caller", ""))
                    if event.get("category") == "message" and event.get("event_type") in {"llm.ai.response", "ai_message"} and not caller.startswith("middleware:"):
                        result[run_id] = event["seq"]
                        break
            return result

        return await asyncio.to_thread(_scan)

    async def count_messages(self, thread_id):
        '''统计线程所有运行文件中的消息事件数量。'''
        all_events = await asyncio.to_thread(self._read_thread_events, thread_id)
        return sum(1 for e in all_events if e.get("category") == "message")

    async def delete_by_thread(self, thread_id):
        '''删除线程全部事件文件并清除该线程的序号和写锁缓存。'''
        async with self._get_write_lock(thread_id):
            all_events = await asyncio.to_thread(self._read_thread_events, thread_id)
            count = len(all_events)
            await asyncio.to_thread(self._delete_thread_files, thread_id)
            self._seq_counters.pop(thread_id, None)
            self._write_locks.pop(thread_id, None)
            return count

    async def delete_by_run(self, thread_id, run_id):
        '''删除单个运行文件并返回其中原有事件数。'''
        async with self._get_write_lock(thread_id):
            events = await asyncio.to_thread(self._read_run_events, thread_id, run_id)
            count = len(events)
            await asyncio.to_thread(self._delete_run_file, thread_id, run_id)
            return count
