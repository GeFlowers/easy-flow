'''

RunEventStore 的内存实现，用于 run_events.backend=memory（默认值）及测试。

适用于单进程异步使用；所有修改均在同一事件循环中完成，无需线程锁。
'''

from __future__ import annotations

import bisect
from datetime import UTC, datetime

from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.user_context import AUTO, _AutoSentinel


class MemoryRunEventStore(RunEventStore):

    def __init__(self) -> None:
        '''初始化事件、消息及运行级排序索引。'''
        self._events: dict[str, list[dict]] = {}
        self._messages: dict[str, list[dict]] = {}
        self._events_by_run: dict[str, dict[str, list[dict]]] = {}
        self._messages_by_run: dict[str, dict[str, list[dict]]] = {}
        self._seq_counters: dict[str, int] = {}

    def _next_seq(self, thread_id: str) -> int:
        '''为线程内新事件递增分配序号。'''
        current = self._seq_counters.get(thread_id, 0)
        next_val = current + 1
        self._seq_counters[thread_id] = next_val
        return next_val

    def _put_one(
        self,
        *,
        thread_id: str,
        run_id: str,
        event_type: str,
        category: str,
        content: str | dict = "",
        metadata: dict | None = None,
        created_at: str | None = None,
    ) -> dict:
        '''创建事件记录并同步更新线程和运行的消息索引。'''
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
        self._events.setdefault(thread_id, []).append(record)
        self._events_by_run.setdefault(thread_id, {}).setdefault(run_id, []).append(record)
        if category == "message":
            self._messages.setdefault(thread_id, []).append(record)
            self._messages_by_run.setdefault(thread_id, {}).setdefault(run_id, []).append(record)
        return record

    async def put(
        self,
        *,
        thread_id,
        run_id,
        event_type,
        category,
        content="",
        metadata=None,
        created_at=None,
    ):
        '''将单条事件写入内存索引并返回记录。'''
        return self._put_one(
            thread_id=thread_id,
            run_id=run_id,
            event_type=event_type,
            category=category,
            content=content,
            metadata=metadata,
            created_at=created_at,
        )

    async def put_batch(self, events):
        '''按输入顺序写入多条事件，并返回生成的记录列表。'''
        results = []
        for ev in events:
            record = self._put_one(**ev)
            results.append(record)
        return results

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None, user_id: str | None | _AutoSentinel = AUTO):
        '''利用线程消息索引和二分查找按序号游标分页。'''
        messages = self._messages.get(thread_id, [])

        if before_seq is not None:
            hi = bisect.bisect_left(messages, before_seq, key=lambda e: e["seq"])
            return messages[max(0, hi - limit) : hi]
        elif after_seq is not None:
            lo = bisect.bisect_right(messages, after_seq, key=lambda e: e["seq"])
            return messages[lo : lo + limit]
        else:
            return messages[-limit:]

    async def list_events(self, thread_id, run_id, *, event_types=None, task_id=None, limit=500, after_seq=None):
        '''从运行级索引读取事件，并按类型、子任务和序号游标过滤。'''
        run_events = self._events_by_run.get(thread_id, {}).get(run_id, [])
        if event_types is not None:
            run_events = [e for e in run_events if e["event_type"] in event_types]
        if task_id is not None:
            run_events = [e for e in run_events if (e.get("metadata") or {}).get("task_id") == task_id]
        if after_seq is not None:
            run_events = [e for e in run_events if e.get("seq", 0) > after_seq]
        return run_events[:limit]

    async def list_messages_by_run(self, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None):
        '''利用运行级消息索引按序号范围返回分页结果。'''
        messages = self._messages_by_run.get(thread_id, {}).get(run_id, [])
        lo = 0 if after_seq is None else bisect.bisect_right(messages, after_seq, key=lambda e: e["seq"])
        hi = len(messages) if before_seq is None else bisect.bisect_left(messages, before_seq, key=lambda e: e["seq"])
        window = messages[lo:hi]
        if after_seq is not None:
            return window[:limit]
        return window[-limit:]

    async def get_last_visible_ai_seq_by_run(self, thread_id, run_ids, *, user_id: str | None | _AutoSentinel = AUTO):
        '''为指定运行批量找出最近一条非中间件助手回复的序号。'''
        result: dict[str, int] = {}
        messages_by_run = self._messages_by_run.get(thread_id, {})
        for run_id in run_ids:
            for event in reversed(messages_by_run.get(run_id, [])):
                caller = str((event.get("metadata") or {}).get("caller", ""))
                if event.get("category") == "message" and event.get("event_type") in {"llm.ai.response", "ai_message"} and not caller.startswith("middleware:"):
                    result[run_id] = event["seq"]
                    break
        return result

    async def count_messages(self, thread_id):
        '''返回线程当前消息索引中的记录数。'''
        return len(self._messages.get(thread_id, []))

    async def delete_by_thread(self, thread_id):
        '''删除线程的全部事件、派生索引和序号计数器。'''
        events = self._events.pop(thread_id, [])
        self._messages.pop(thread_id, None)
        self._events_by_run.pop(thread_id, None)
        self._messages_by_run.pop(thread_id, None)
        self._seq_counters.pop(thread_id, None)
        return len(events)

    async def delete_by_run(self, thread_id, run_id):
        '''删除指定运行事件并同步重建线程消息索引、清理运行索引。'''
        all_events = self._events.get(thread_id, [])
        if not all_events:
            return 0
        remaining = [e for e in all_events if e["run_id"] != run_id]
        removed = len(all_events) - len(remaining)
        self._events[thread_id] = remaining
        self._messages[thread_id] = [e for e in remaining if e["category"] == "message"]
        self._events_by_run.get(thread_id, {}).pop(run_id, None)
        self._messages_by_run.get(thread_id, {}).pop(run_id, None)
        return removed
