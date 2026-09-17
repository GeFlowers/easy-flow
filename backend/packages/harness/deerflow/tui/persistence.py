"未说明"

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import Any

from deerflow.runtime.user_context import DEFAULT_USER_ID


class _LoopThread:
    "未说明"

    def __init__(self) -> None:
        "未说明"
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="deerflow-tui-db", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        "未说明"
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Awaitable[Any], *, timeout: float = 15.0) -> Any:
        "未说明"
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

    def close(self) -> None:
        "未说明"
        self._loop.call_soon_threadsafe(self._loop.stop)


class ThreadMetaWriter:
    "未说明"

    def __init__(self, loop: _LoopThread, store: Any) -> None:
        "未说明"
        self._loop = loop
        self._store = store
        self.user_id = DEFAULT_USER_ID

    @property
    def enabled(self) -> bool:
        "未说明"
        return self._store is not None

    def ensure_created(self, thread_id: str, *, assistant_id: str | None = None, metadata: dict | None = None) -> None:
        "未说明"
        if not self._store or not thread_id:
            return
        try:
            self._loop.run(self._ensure_created(thread_id, assistant_id, metadata))
        except Exception:  # noqa: BLE001 - best-effort
            pass

    async def _ensure_created(self, thread_id: str, assistant_id: str | None, metadata: dict | None) -> None:
        "未说明"
        existing = await self._store.get(thread_id, user_id=self.user_id)
        if existing is None:
            await self._store.create(
                thread_id,
                assistant_id=assistant_id,
                user_id=self.user_id,
                metadata=metadata or {"source": "tui"},
            )

    def set_title(self, thread_id: str, title: str) -> None:
        "未说明"
        if not self._store or not thread_id or not title:
            return
        try:
            self._loop.run(self._store.update_display_name(thread_id, title, user_id=self.user_id))
        except Exception:  # noqa: BLE001 - best-effort
            pass


def build_persistence() -> tuple[_LoopThread, ThreadMetaWriter]:
    "未说明"
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
