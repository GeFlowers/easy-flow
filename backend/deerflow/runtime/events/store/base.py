'''

运行事件存储的抽象接口。

RunEventStore 是运行事件流的统一存储接口。用于前端展示的消息与用于
调试、审计的执行追踪均通过此接口保存，由 ``category`` 字段区分。

实现：
- MemoryRunEventStore：内存字典，供开发和测试使用。
- DbRunEventStore：基于 SQLAlchemy 的数据库存储。
- JsonlRunEventStore：逐行保存事件的文件存储。
'''

from __future__ import annotations

import abc

from deerflow.runtime.user_context import AUTO, _AutoSentinel


class RunEventStore(abc.ABC):
    '''

    运行事件流存储接口。

        所有实现必须保证：
        1. put() 写入的事件可在后续查询中读取。
        2. 同一线程内 seq 严格递增。
        3. list_messages() 仅返回 category="message" 的事件。
        4. list_events() 返回指定运行中符合筛选和分页条件的事件。
        5. 返回字典符合 RunEvent 字段结构。
    '''

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
        '''

        写入事件，自动分配 seq，并返回完整记录。'''

    @abc.abstractmethod
    async def put_batch(self, events: list[dict]) -> list[dict]:
        '''

        批量写入同一刷新批次的事件，减少逐条提交的事务开销。

                每个字典的键与 put() 的关键字参数一致。
                返回已分配 seq 的完整记录。
        '''

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
        '''

        返回线程的可展示消息（category=message），按 seq 升序排列。

                支持双向游标分页：
                - before_seq: 返回 seq < before_seq 的最后 ``limit`` 条记录（升序）。
                - after_seq: 返回 seq > after_seq 的最前 ``limit`` 条记录（升序）。
                - 均未提供：返回最近 ``limit`` 条记录（升序）。

                不依赖请求的调用方可显式传入 ``user_id``；
                按用户隔离的后端必须依照其隔离模型应用此参数。
        '''

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
        '''

        返回运行的事件流，按 seq 升序排列。

                可按 ``event_types`` 和／或 ``task_id`` 筛选，后者匹配
                ``metadata["task_id"]``。``after_seq`` 是向前游标，返回
                seq > after_seq 的最前 ``limit`` 条记录，使调用方可分页读取
                单个子智能体任务的事件，避免运行级 ``limit`` 截断尾部（#3779）。
        '''

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
        '''

        返回指定运行的可展示消息（category=message），按 seq 升序排列。

                支持双向游标分页：
                - after_seq: 返回 seq > after_seq 的最前 ``limit`` 条记录（升序）。
                - before_seq: 返回 seq < before_seq 的最后 ``limit`` 条记录（升序）。
                - 均未提供：返回最近 ``limit`` 条记录（升序）。
        '''

    @abc.abstractmethod
    async def get_last_visible_ai_seq_by_run(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, int]:
        '''

        返回每个运行最后一条非中间件助手消息的序号。

                ``user_id`` 的显式传入语义与 :meth:`list_messages` 相同。
        '''

    @abc.abstractmethod
    async def count_messages(self, thread_id: str) -> int:
        '''

        统计线程中的可展示消息（category=message）数量。'''

    @abc.abstractmethod
    async def delete_by_thread(self, thread_id: str) -> int:
        '''

        删除线程的全部事件，返回删除的事件数。'''

    @abc.abstractmethod
    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        '''

        删除指定运行的全部事件，返回删除的事件数。'''
