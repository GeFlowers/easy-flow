'''为有状态工具调用维护持久化 MCP 会话池。

通过 langchain-mcp-adapters 以 ``session=None`` 加载 MCP 工具时，每次工具调用
都会创建新的 MCP 会话。对于 Playwright 等有状态服务器，这会导致已打开的页面、已
填写的表单等浏览器状态在调用间丢失。

本模块按 ``(server_name, scope_key)`` 维护持久化 MCP 会话；``scope_key`` 通常为
``thread_id``，因此同一作用域内连续的工具调用可共享会话及服务端状态。池达到容量
上限时，按 LRU 顺序逐出会话。

生命周期模型（所有者任务）
--------------------------
MCP ``ClientSession`` 建立在 ``anyio`` 任务组之上。anyio 要求取消作用域必须由进入
它的*同一任务*退出；若由执行 ``cm.__aenter__`` 之外的任务调用 ``cm.__aexit__``，将
抛出错误。

同步工具路径（``make_sync_tool_wrapper``）会通过新的 ``asyncio.run`` 事件循环执行
每次调用，因此某次调用中进入的会话若在另一次调用中退出，会因任务不同而崩溃
（GitHub 问题 #3379）。

为避免该问题，每个池化会话均由专用的 ``_run_session`` 任务持有。该任务进入上下文
管理器，将活动会话交给调用方后等待关闭事件。所有关闭路径只会**发出**该事件；由
所有者任务自行执行 ``__aexit__``，确保进入和退出始终发生在同一任务中。
'''

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from typing import Any

from mcp import ClientSession

logger = logging.getLogger(__name__)


class MCPSessionPool:
    '''按 ``(server_name, scope_key)`` 管理持久化 MCP 会话。'''

    MAX_SESSIONS = 256
    SESSION_CLOSE_TIMEOUT = 5.0

    def __init__(self) -> None:
        '''初始化会话条目、进行中的创建记录及线程同步锁。'''
        self._entries: OrderedDict[
            tuple[str, str],
            tuple[
                ClientSession,
                asyncio.AbstractEventLoop,
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = OrderedDict()
        self._inflight: dict[
            tuple[str, str],
            tuple[
                asyncio.AbstractEventLoop,
                asyncio.Future[ClientSession],
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = {}
        self._lock = threading.Lock()


    async def _run_session(
        self,
        connection: dict[str, Any],
        ready: asyncio.Future[ClientSession],
        close_evt: asyncio.Event,
    ) -> None:
        '''在整个生命周期内由当前任务独占一个 MCP 会话。

        此方法进入并初始化会话上下文管理器，通过 ``ready`` 发布活动会话，随后等待
        ``close_evt`` 被设置。上下文管理器始终由当前任务退出，以满足 anyio 对取消
        作用域“同一任务退出”的要求。
        '''
        from langchain_mcp_adapters.sessions import create_session

        cm = create_session(connection)
        try:
            session = await cm.__aenter__()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e)
            return

        try:
            await session.initialize()
            if not ready.done():
                ready.set_result(session)
            await close_evt.wait()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e)
        finally:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing MCP session", exc_info=True)

    async def get_session(
        self,
        server_name: str,
        scope_key: str,
        connection: dict[str, Any],
    ) -> ClientSession:
        '''获取或创建持久化 MCP 会话。

        若已有会话创建于不同或已关闭的事件循环，将其逐出，并在当前事件循环上由新任务
        创建替代会话。

        参数：
            server_name：MCP 服务器名称。
            scope_key：隔离键，通常为 thread_id。
            connection：传给 ``create_session`` 的连接配置。

        返回：
            已完成初始化的 ``ClientSession``。
        '''
        key = (server_name, scope_key)
        current_loop = asyncio.get_running_loop()

        evicted: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event, bool]] = []
        join: asyncio.Future[ClientSession] | None = None
        ready: asyncio.Future[ClientSession] | None = None
        close_evt: asyncio.Event | None = None
        task: asyncio.Task[Any] | None = None
        with self._lock:
            if key in self._entries:
                session, loop, ent_task, ent_close = self._entries[key]
                if loop is current_loop and not loop.is_closed():
                    self._entries.move_to_end(key)
                    return session
                self._entries.pop(key)
                evicted.append((loop, ent_task, ent_close, False))

            inflight = self._inflight.get(key)
            if inflight is not None and inflight[0] is current_loop and not inflight[0].is_closed():
                join = inflight[1]
            else:
                if inflight is not None:
                    self._inflight.pop(key)
                    evicted.append((inflight[0], inflight[2], inflight[3], True))
                ready = current_loop.create_future()
                close_evt = asyncio.Event()
                task = current_loop.create_task(self._run_session(connection, ready, close_evt))
                self._inflight[key] = (current_loop, ready, task, close_evt)

            while len(self._entries) >= self.MAX_SESSIONS:
                oldest_key, (_, loop, ent_task, ent_close) = next(iter(self._entries.items()))
                self._entries.pop(oldest_key)
                evicted.append((loop, ent_task, ent_close, False))

        for loop, ent_task, ent_close, cancel in evicted:
            if loop is current_loop and not loop.is_closed():
                await self._shutdown(ent_close, ent_task, cancel)
            elif cancel:
                await self._shutdown_entry(loop, ent_task, ent_close, cancel=True)
            else:
                self._signal_close(loop, ent_close)

        if join is not None:
            return await asyncio.shield(join)

        assert ready is not None and close_evt is not None and task is not None

        try:
            session = await asyncio.shield(ready)
        except BaseException:
            owner_already_failed = ready.done() and not ready.cancelled() and ready.exception() is not None
            if not owner_already_failed:
                close_evt.set()
                task.cancel()
            try:
                await asyncio.shield(task)
            except BaseException:
                logger.debug("Owner task ended during get_session unwind", exc_info=True)
            with self._lock:
                if self._inflight.get(key) == (current_loop, ready, task, close_evt):
                    self._inflight.pop(key)
            raise

        with self._lock:
            still_ours = self._inflight.get(key) == (current_loop, ready, task, close_evt)
            if still_ours:
                self._inflight.pop(key)
                self._entries[key] = (session, current_loop, task, close_evt)
        if not still_ours:
            await self._shutdown(close_evt, task)
            raise asyncio.CancelledError("MCP session pool was closed while the session was being created")
        logger.info("Created persistent MCP session for %s/%s", server_name, scope_key)
        return session


    @staticmethod
    def _signal_close(loop: asyncio.AbstractEventLoop, close_evt: asyncio.Event) -> None:
        '''请求所有者任务关闭，但不等待其完成。

        ``asyncio.Event.set`` 不是线程安全操作，因此需调度到所有者事件循环。事件循环
        已关闭则表示所有者任务已经结束。
        '''
        if loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(close_evt.set)
        except RuntimeError:
            pass

    async def _shutdown(
        self,
        close_evt: asyncio.Event,
        task: asyncio.Task[Any],
        cancel: bool = False,
    ) -> None:
        '''向所有者任务发送关闭信号，并在其事件循环上等待结束。

        ``cancel=True`` 用于尚在创建中的会话：所有者任务可能阻塞在 ``initialize()``
        中，无法被 ``close_evt`` 唤醒，因而必须取消。其 ``finally`` 块仍会在自身任务
        中执行 ``__aexit__``，满足 anyio 对取消作用域“同一任务退出”的要求。
        '''
        close_evt.set()
        if cancel:
            task.cancel()
        try:
            await task
        except (Exception, asyncio.CancelledError):
            logger.debug("Owner task ended during shutdown", exc_info=True)

    async def _shutdown_entry(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task[Any],
        close_evt: asyncio.Event,
        cancel: bool = False,
    ) -> None:
        '''将单个条目的关闭操作路由到其所属事件循环执行。'''
        if loop.is_closed():
            return
        current_loop = asyncio.get_running_loop()
        if loop is current_loop:
            await self._shutdown(close_evt, task, cancel)
        elif loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(close_evt, task, cancel), loop)
            try:
                await asyncio.wrap_future(future)
            except Exception:
                logger.warning("Error closing MCP session on owning loop", exc_info=True)
        else:
            logger.warning("Owning loop for MCP session is idle; signalling close best-effort. Session may leak until the loop runs again.")
            self._signal_close(loop, close_evt)
            if cancel:
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass

    async def close_scope(self, scope_key: str) -> None:
        '''关闭指定作用域（例如 thread_id）的全部会话。'''
        with self._lock:
            keys = [k for k in self._entries if k[1] == scope_key]
            entries = [(self._entries.pop(k)) for k in keys]
            inflight_keys = [k for k in self._inflight if k[1] == scope_key]
            inflight = [self._inflight.pop(k) for k in inflight_keys]
        for _session, loop, task, close_evt in entries:
            await self._shutdown_entry(loop, task, close_evt)
        for loop, _ready, task, close_evt in inflight:
            await self._shutdown_entry(loop, task, close_evt, cancel=True)

    async def close_server(self, server_name: str) -> None:
        '''关闭指定服务器的全部会话。'''
        with self._lock:
            keys = [k for k in self._entries if k[0] == server_name]
            entries = [(self._entries.pop(k)) for k in keys]
            inflight_keys = [k for k in self._inflight if k[0] == server_name]
            inflight = [self._inflight.pop(k) for k in inflight_keys]
        for _session, loop, task, close_evt in entries:
            await self._shutdown_entry(loop, task, close_evt)
        for loop, _ready, task, close_evt in inflight:
            await self._shutdown_entry(loop, task, close_evt, cancel=True)

    async def close_all(self) -> None:
        '''关闭当前管理的全部会话。'''
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()
        for _session, loop, task, close_evt in entries:
            await self._shutdown_entry(loop, task, close_evt)
        for loop, _ready, task, close_evt in inflight:
            await self._shutdown_entry(loop, task, close_evt, cancel=True)

    def close_all_sync(self) -> None:
        '''同步地在各会话所属事件循环上关闭全部会话。

        每个会话均由其所有者任务在创建它的事件循环中关闭，从而避免跨事件循环和跨任务错误。
        此方法可从没有活动事件循环的任意线程安全调用。

        关闭语义取决于所有者事件循环的运行位置：

        * 所有者事件循环空闲或运行在其他线程时，本调用会阻塞至清理完成，或达到
          ``SESSION_CLOSE_TIMEOUT``。
        * 所有者事件循环正在*当前*线程运行时，不能等待，否则会死锁；此处仅发送关闭信号，
          待控制权返回该事件循环后异步完成。因此调用者必须继续运行该循环；若立即停止循环，
          所有者任务的 ``__aexit__`` 可能不会执行。若需在运行中的事件循环内确定性关闭，请改用
          ``await close_all()``。
        '''
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()

        owners = [(loop, task, close_evt, False) for _s, loop, task, close_evt in entries]
        owners += [(loop, task, close_evt, True) for loop, _r, task, close_evt in inflight]
        try:
            current_running_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_running_loop = None
        for loop, task, close_evt, cancel in owners:
            if loop.is_closed():
                continue
            try:
                if loop is current_running_loop:
                    close_evt.set()
                    if cancel:
                        task.cancel()
                elif loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self._shutdown(close_evt, task, cancel), loop)
                    future.result(timeout=self.SESSION_CLOSE_TIMEOUT)
                else:
                    loop.run_until_complete(self._shutdown(close_evt, task, cancel))
            except Exception:
                logger.debug("Error closing MCP session during sync close", exc_info=True)



_pool: MCPSessionPool | None = None
_pool_lock = threading.Lock()


def get_session_pool() -> MCPSessionPool:
    '''返回全局会话池单例。'''
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = MCPSessionPool()
        return _pool


def reset_session_pool() -> None:
    '''重置全局会话池单例，供测试和 MCP 缓存重置路径使用。'''
    global _pool
    with _pool_lock:
        _pool = None
