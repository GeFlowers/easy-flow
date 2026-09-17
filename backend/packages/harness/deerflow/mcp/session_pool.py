"""为有状态工具调用维护持久化 MCP 会话池。

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
（GitHub issue #3379）。

为避免该问题，每个池化会话均由专用的 ``_run_session`` 任务持有。该任务进入上下文
管理器，将活动会话交给调用方后等待关闭事件。所有关闭路径只会**发出**该事件；由
所有者任务自行执行 ``__aexit__``，确保进入和退出始终发生在同一任务中。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from typing import Any

from mcp import ClientSession

logger = logging.getLogger(__name__)


class MCPSessionPool:
    """按 ``(server_name, scope_key)`` 管理持久化 MCP 会话。"""

    MAX_SESSIONS = 256
    SESSION_CLOSE_TIMEOUT = 5.0  # seconds to wait when closing a session on a foreign loop

    def __init__(self) -> None:
        # Each entry: (session, owning_loop, owner_task, close_event).
        """初始化会话条目、进行中的创建记录及线程同步锁。"""
        self._entries: OrderedDict[
            tuple[str, str],
            tuple[
                ClientSession,
                asyncio.AbstractEventLoop,
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = OrderedDict()
        # In-flight creations, keyed by (server, scope). Lets concurrent callers
        # on the same loop share a single creation instead of each spawning a
        # duplicate session. Value: (loop, ready_future, owner_task, close_event).
        self._inflight: dict[
            tuple[str, str],
            tuple[
                asyncio.AbstractEventLoop,
                asyncio.Future[ClientSession],
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = {}
        # threading.Lock is not bound to any event loop, so it is safe to
        # acquire from both async paths and sync/worker-thread paths.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Session owner task
    # ------------------------------------------------------------------

    async def _run_session(
        self,
        connection: dict[str, Any],
        ready: asyncio.Future[ClientSession],
        close_evt: asyncio.Event,
    ) -> None:
        """在整个生命周期内由当前任务独占一个 MCP 会话。

        此方法进入并初始化会话上下文管理器，通过 ``ready`` 发布活动会话，随后等待
        ``close_evt`` 被设置。上下文管理器始终由当前任务退出，以满足 anyio 对取消
        作用域“同一任务退出”的要求。
        """
        from langchain_mcp_adapters.sessions import create_session

        cm = create_session(connection)
        try:
            session = await cm.__aenter__()
        except BaseException as e:
            # Never entered the cancel scope, so there is nothing to exit.
            if not ready.done():
                ready.set_exception(e)
            return

        # The context manager is now entered. From here on __aexit__ MUST run in
        # this task — on init failure, on cancellation, or on the close signal —
        # to satisfy anyio's same-task cancel-scope requirement and to avoid
        # leaking the session/subprocess.
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
        """获取或创建持久化 MCP 会话。

        若已有会话创建于不同或已关闭的事件循环，将其逐出，并在当前事件循环上由新任务
        创建替代会话。

        参数：
            server_name：MCP 服务器名称。
            scope_key：隔离键，通常为 thread_id。
            connection：传给 ``create_session`` 的连接配置。

        返回：
            已完成初始化的 ``ClientSession``。
        """
        key = (server_name, scope_key)
        current_loop = asyncio.get_running_loop()

        # Phase 1: inspect/mutate the registry under the thread lock (no awaits).
        # Decide one of three outcomes atomically: return an existing session,
        # join an in-flight creation, or become the creator for this key.
        # Each item: (loop, owner_task, close_event, cancel). ``cancel`` is True
        # for in-flight creations, whose owner may be blocked inside
        # ``initialize()`` where close_evt cannot wake it — it must be cancelled.
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
                # Session belongs to a different/closed event loop – evict it.
                self._entries.pop(key)
                evicted.append((loop, ent_task, ent_close, False))

            inflight = self._inflight.get(key)
            if inflight is not None and inflight[0] is current_loop and not inflight[0].is_closed():
                # Another caller on this loop is already creating the session;
                # wait for the same result instead of building a duplicate.
                join = inflight[1]
            else:
                if inflight is not None:
                    # Stale in-flight creation owned by a different/closed loop.
                    # Drop the record and tear its owner down; because that owner
                    # may be blocked inside initialize() (where close_evt cannot
                    # wake it), it must be cancelled. We then create a fresh
                    # session here.
                    self._inflight.pop(key)
                    evicted.append((inflight[0], inflight[2], inflight[3], True))
                # Become the creator: publish an in-flight record before any
                # await so concurrent callers join us instead of racing.
                ready = current_loop.create_future()
                close_evt = asyncio.Event()
                task = current_loop.create_task(self._run_session(connection, ready, close_evt))
                self._inflight[key] = (current_loop, ready, task, close_evt)

            # Evict LRU entries when at capacity.
            while len(self._entries) >= self.MAX_SESSIONS:
                oldest_key, (_, loop, ent_task, ent_close) = next(iter(self._entries.items()))
                self._entries.pop(oldest_key)
                evicted.append((loop, ent_task, ent_close, False))

        # Phase 2: shut down evicted sessions/creations. Same-loop owners are
        # awaited so they finish deterministically; foreign-loop owners are
        # routed to their own loop. In every case the owner task — never this
        # one — runs __aexit__. In-flight owners are cancelled (cancel=True) so a
        # blocking initialize() cannot leave them hung.
        for loop, ent_task, ent_close, cancel in evicted:
            if loop is current_loop and not loop.is_closed():
                await self._shutdown(ent_close, ent_task, cancel)
            elif cancel:
                await self._shutdown_entry(loop, ent_task, ent_close, cancel=True)
            else:
                self._signal_close(loop, ent_close)

        # Phase 2b: a concurrent creation for this key is already in progress on
        # this loop — share its result rather than create a duplicate session.
        if join is not None:
            return await asyncio.shield(join)

        assert ready is not None and close_evt is not None and task is not None

        # Phase 3: wait for our owner task to publish the initialized session.
        try:
            session = await asyncio.shield(ready)
        except BaseException:
            # Two distinct cases reach here:
            #
            # 1. The owner task failed (e.g. connect/initialize error) and
            #    reported it via ready.set_exception(). It is *already* in its
            #    finally block running cm.__aexit__ in its own task, so we must
            #    NOT cancel it — doing so would interrupt that cleanup. We only
            #    wait for it to finish unwinding.
            # 2. This call itself was cancelled (CancelledError). Because of the
            #    shield, `ready` is still pending and the owner task is alive and
            #    blocked. We signal close and cancel it so it exits the cancel
            #    scope in its own task, then wait for it to finish.
            #
            # The session is never registered yet, so nobody else can close it;
            # waiting here guarantees we never leak a session or owner task.
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

        # Phase 4: promote the in-flight creation to a registered entry — but
        # only if our in-flight record is still the live one. A concurrent
        # close_* / close_all may have removed it while we were initializing; in
        # that case we must NOT resurrect the session into _entries. Instead we
        # own the teardown: signal our owner task and wait for it to run
        # __aexit__ in its own task, then surface the cancellation.
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

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _signal_close(loop: asyncio.AbstractEventLoop, close_evt: asyncio.Event) -> None:
        """请求所有者任务关闭，但不等待其完成。

        ``asyncio.Event.set`` 不是线程安全操作，因此需调度到所有者事件循环。事件循环
        已关闭则表示所有者任务已经结束。
        """
        if loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(close_evt.set)
        except RuntimeError:
            # Loop was closed between the is_closed() check and now.
            pass

    async def _shutdown(
        self,
        close_evt: asyncio.Event,
        task: asyncio.Task[Any],
        cancel: bool = False,
    ) -> None:
        """向所有者任务发送关闭信号，并在其事件循环上等待结束。

        ``cancel=True`` 用于尚在创建中的会话：所有者任务可能阻塞在 ``initialize()``
        中，无法被 ``close_evt`` 唤醒，因而必须取消。其 ``finally`` 块仍会在自身任务
        中执行 ``__aexit__``，满足 anyio 对取消作用域“同一任务退出”的要求。
        """
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
        """将单个条目的关闭操作路由到其所属事件循环执行。"""
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
            # Owning loop exists but is neither the current loop nor running.
            # We are inside an async context here, so run_until_complete() would
            # raise "Cannot run the event loop while another loop is running";
            # and the loop may belong to another thread, where driving it from
            # here is unsafe. This branch is not expected in practice — a
            # session's owning loop is either the long-lived gateway loop (which
            # is running) or a short-lived asyncio.run loop (which is closed and
            # caught above). Fall back to a best-effort thread-safe signal so the
            # owner task tears down if/when its loop runs again.
            logger.warning("Owning loop for MCP session is idle; signalling close best-effort. Session may leak until the loop runs again.")
            self._signal_close(loop, close_evt)
            if cancel:
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass

    async def close_scope(self, scope_key: str) -> None:
        """关闭指定作用域（例如 thread_id）的全部会话。"""
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
        """关闭指定服务器的全部会话。"""
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
        """关闭当前管理的全部会话。"""
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
        """同步地在各会话所属事件循环上关闭全部会话。

        每个会话均由其所有者任务在创建它的事件循环中关闭，从而避免跨事件循环和跨任务错误。
        此方法可从没有活动事件循环的任意线程安全调用。

        关闭语义取决于所有者事件循环的运行位置：

        * 所有者事件循环空闲或运行在其他线程时，本调用会阻塞至清理完成，或达到
          ``SESSION_CLOSE_TIMEOUT``。
        * 所有者事件循环正在*当前*线程运行时，不能等待，否则会死锁；此处仅发送关闭信号，
          待控制权返回该事件循环后异步完成。因此调用者必须继续运行该循环；若立即停止循环，
          所有者任务的 ``__aexit__`` 可能不会执行。若需在运行中的事件循环内确定性关闭，请改用
          ``await close_all()``。
        """
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()

        # Entries are initialized (gentle close_evt path). In-flight creations
        # may be blocked mid-init, so they are cancelled to unblock teardown.
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
                    # We are executing inside this loop's thread, so synchronously
                    # waiting on run_coroutine_threadsafe(...).result() would
                    # deadlock until timeout. Signal the owner task directly and
                    # let it finish once this synchronous call returns control to
                    # the running loop.
                    close_evt.set()
                    if cancel:
                        task.cancel()
                elif loop.is_running():
                    # Schedule the shutdown on the owning loop from this thread.
                    future = asyncio.run_coroutine_threadsafe(self._shutdown(close_evt, task, cancel), loop)
                    future.result(timeout=self.SESSION_CLOSE_TIMEOUT)
                else:
                    loop.run_until_complete(self._shutdown(close_evt, task, cancel))
            except Exception:
                logger.debug("Error closing MCP session during sync close", exc_info=True)


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_pool: MCPSessionPool | None = None
_pool_lock = threading.Lock()


def get_session_pool() -> MCPSessionPool:
    """返回全局会话池单例。"""
    global _pool
    # Build and return under the lock so racing cold-start callers construct
    # exactly one pool and reset_session_pool() can't null the global between
    # reading it and returning it (which previously could hand back None). The
    # critical section is tiny and never awaits, so a threading.Lock is safe to
    # hold from both the async and sync/worker-thread paths.
    with _pool_lock:
        if _pool is None:
            _pool = MCPSessionPool()
        return _pool


def reset_session_pool() -> None:
    """重置全局会话池单例，供测试和 MCP 缓存重置路径使用。"""
    global _pool
    with _pool_lock:
        _pool = None
