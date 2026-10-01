'''为终端界面提供跨线程的异步数据库调用，以及线程元数据的尽力写入。'''

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import Any

from deerflow.runtime.user_context import DEFAULT_USER_ID


class _LoopThread:
    '''在后台线程持续运行专属异步事件循环，供同步终端代码调用异步持久化接口。'''

    def __init__(self) -> None:
        '''创建新的异步事件循环并在线程中启动循环执行器。'''
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="deerflow-tui-db", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        '''将当前线程绑定到事件循环并持续处理待执行协程。'''
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Awaitable[Any], *, timeout: float = 15.0) -> Any:
        '''在线程安全的事件循环中提交协程，并等待结果或超时。'''
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

    def close(self) -> None:
        '''向事件循环线程发送停止请求。'''
        self._loop.call_soon_threadsafe(self._loop.stop)


class ThreadMetaWriter:
    '''通过后台事件循环维护终端界面创建和重命名的线程元数据。'''

    def __init__(self, loop: _LoopThread, store: Any) -> None:
        '''保存事件循环桥和可选线程元数据存储，并使用默认用户标识。'''
        self._loop = loop
        self._store = store
        self.user_id = DEFAULT_USER_ID

    @property
    def enabled(self) -> bool:
        '''指示是否已连接线程元数据存储。'''
        return self._store is not None

    def ensure_created(self, thread_id: str, *, assistant_id: str | None = None, metadata: dict | None = None) -> None:
        '''同步确保线程记录已存在；持久化失败时不影响终端会话。'''
        if not self._store or not thread_id:
            return
        try:
            self._loop.run(self._ensure_created(thread_id, assistant_id, metadata))
        except Exception:  # noqa: BLE001 - best-effort
            pass

    async def _ensure_created(self, thread_id: str, assistant_id: str | None, metadata: dict | None) -> None:
        '''查询线程记录，仅在尚不存在时创建并写入终端来源元数据。'''
        existing = await self._store.get(thread_id, user_id=self.user_id)
        if existing is None:
            await self._store.create(
                thread_id,
                assistant_id=assistant_id,
                user_id=self.user_id,
                metadata=metadata or {"source": "tui"},
            )

    def set_title(self, thread_id: str, title: str) -> None:
        '''尽力更新线程显示名称，缺少必要参数或数据库故障时安静返回。'''
        if not self._store or not thread_id or not title:
            return
        try:
            self._loop.run(self._store.update_display_name(thread_id, title, user_id=self.user_id))
        except Exception:  # noqa: BLE001 - best-effort
            pass


def build_persistence() -> tuple[_LoopThread, ThreadMetaWriter]:
    '''初始化终端界面的数据库引擎和线程元数据写入器，失败时退化为无持久化写入。'''
    loop = _LoopThread()
    store = None
    try:
        from deerflow.config.app_config import get_app_config
        from deerflow.persistence.engine import get_session_factory, init_engine_from_config
        from deerflow.persistence.thread_meta import make_thread_store

        config = get_app_config()
        loop.run(init_engine_from_config(config.database))
        session_factory = get_session_factory()
        if session_factory is not None:
            store = make_thread_store(session_factory)
    except Exception:  # noqa: BLE001 - degrade to no-op writer
        store = None
    return loop, ThreadMetaWriter(loop, store)
