'''组合终端客户端、线程元数据持久化和资源关闭逻辑。'''

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.client import DeerFlowClient

    from .cli import LaunchPlan
    from .persistence import ThreadMetaWriter, _LoopThread


@dataclass
class Session:
    '''保存终端客户端及其可选的持久化写入器和后台事件循环。'''

    client: DeerFlowClient
    writer: ThreadMetaWriter | None = None
    _loop: _LoopThread | None = None

    def resolve_thread(self, plan: LaunchPlan) -> str | None:
        '''按显式线程标识或最近线程选项解析要打开的会话。'''
        if plan.thread_id:
            return self.resolve_ref(plan.thread_id)
        if plan.continue_recent:
            threads = self.client.list_threads(limit=1).get("thread_list", [])
            if threads:
                return threads[0].get("thread_id")
        return None

    def resolve_ref(self, ref: str) -> str:
        '''按线程标识或标题查找线程；查询失败或未匹配时保留原始输入。'''
        try:
            threads = self.client.list_threads(limit=100).get("thread_list", [])
        except Exception:  # noqa: BLE001 - resolution is best-effort
            return ref
        if any(t.get("thread_id") == ref for t in threads):
            return ref
        for thread in threads:
            if (thread.get("title") or "") == ref:
                return thread.get("thread_id") or ref
        return ref

    def recent_threads(self, limit: int = 20) -> list[dict]:
        '''获取最近线程列表供终端线程切换器展示。'''
        return self.client.list_threads(limit=limit).get("thread_list", [])

    def close(self) -> None:
        '''关闭数据库引擎及后台事件循环，清理错误不会阻止会话退出。'''
        loop = self._loop
        if loop is None:
            return
        self._loop = None
        try:
            from deerflow.persistence.engine import close_engine

            loop.run(close_engine())
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        loop.close()


def open_session(persistence: bool = True) -> Session:
    '''创建终端客户端，并按配置选择是否初始化数据库持久化服务。'''
    from deerflow.client import DeerFlowClient
    from deerflow.runtime.checkpointer.provider import get_checkpointer

    checkpointer = get_checkpointer()
    client = DeerFlowClient(checkpointer=checkpointer)
    if not persistence:
        return Session(client=client)

    from .persistence import build_persistence

    loop, writer = build_persistence()
    return Session(client=client, writer=writer, _loop=loop)
