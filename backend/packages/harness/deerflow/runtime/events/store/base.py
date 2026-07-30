'定义 base 模块提供的职责与可复用接口。\n\nAbstract interface for run event storage.\n\nRunEventStore is the unified storage interface for run event streams.\nMessages (frontend display) and execution traces (debugging/audit) go\nthrough the same interface, distinguished by the ``category`` field.\n\nImplementations:\n- MemoryRunEventStore: in-memory dict (development, tests)\n- Future: DB-backed store (SQLAlchemy ORM), JSONL file store\n'

from __future__ import annotations

import abc

from deerflow.runtime.user_context import AUTO, _AutoSentinel


class RunEventStore(abc.ABC):
    '封装 RunEventStore 的状态、协作关系与公开操作。\n\nRun event stream storage interface.\n\n    All implementations must guarantee:\n    1. put() events are retrievable in subsequent queries\n    2. seq is strictly increasing within the same thread\n    3. list_messages() only returns category="message" events\n    4. list_events() returns all events for the specified run\n    5. Returned dicts match the RunEvent field structure\n    '

    @abc.abstractmethod
    async def put(
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
        '执行 put 的明确职责，并返回与调用约定一致的结果。\n\nWrite an event, auto-assign seq, return the complete record.'

    @abc.abstractmethod
    async def put_batch(self, events: list[dict]) -> list[dict]:
        "执行 put_batch 的明确职责，并返回与调用约定一致的结果。\n\nBatch-write events. Used by RunJournal flush buffer.\n\n        Each dict's keys match put()'s keyword arguments.\n        Returns complete records with seq assigned.\n        "

    @abc.abstractmethod
    async def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        '收集并返回，并遵守 list_messages 所表达的接口约束。\n\nReturn displayable messages (category=message) for a thread, ordered by seq ascending.\n\n        Supports bidirectional cursor pagination:\n        - before_seq: return the last ``limit`` records with seq < before_seq (ascending)\n        - after_seq: return the first ``limit`` records with seq > after_seq (ascending)\n        - neither: return the latest ``limit`` records (ascending)\n\n        ``user_id`` may be passed explicitly by request-independent callers;\n        user-scoped backends must apply it according to their isolation model.\n        '

    @abc.abstractmethod
    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        task_id: str | None = None,
        limit: int = 500,
        after_seq: int | None = None,
    ) -> list[dict]:
        '收集并返回，并遵守 list_events 所表达的接口约束。\n\nReturn the full event stream for a run, ordered by seq ascending.\n\n        Optionally filter by ``event_types`` and/or ``task_id`` (matched against\n        ``metadata["task_id"]``). ``after_seq`` is a forward cursor returning the\n        first ``limit`` records with seq > after_seq, so callers can page through\n        a single subagent task\'s events without the run-wide ``limit`` truncating\n        the tail (#3779).\n        '

    @abc.abstractmethod
    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[dict]:
        '收集并返回，并遵守 list_messages_by_run 所表达的接口约束。\n\nReturn displayable messages (category=message) for a specific run, ordered by seq ascending.\n\n        Supports bidirectional cursor pagination:\n        - after_seq: return the first ``limit`` records with seq > after_seq (ascending)\n        - before_seq: return the last ``limit`` records with seq < before_seq (ascending)\n        - neither: return the latest ``limit`` records (ascending)\n        '

    @abc.abstractmethod
    async def get_last_visible_ai_seq_by_run(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, int]:
        "读取并返回，并遵守 get_last_visible_ai_seq_by_run 所表达的接口约束。\n\nReturn each run's last non-middleware AI message sequence.\n\n        ``user_id`` follows the same explicit-caller semantics as\n        :meth:`list_messages`.\n        "

    @abc.abstractmethod
    async def count_messages(self, thread_id: str) -> int:
        '执行 count_messages 的明确职责，并返回与调用约定一致的结果。\n\nCount displayable messages (category=message) in a thread.'

    @abc.abstractmethod
    async def delete_by_thread(self, thread_id: str) -> int:
        '删除目标资源并返回操作结果，并遵守 delete_by_thread 所表达的接口约束。\n\nDelete all events for a thread. Return the number of deleted events.'

    @abc.abstractmethod
    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        '删除目标资源并返回操作结果，并遵守 delete_by_run 所表达的接口约束。\n\nDelete all events for a specific run. Return the number of deleted events.'
