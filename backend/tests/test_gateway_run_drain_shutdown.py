"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import asyncio
import operator
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from typing import Annotated, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime import RunManager, RunStatus


# 说明当前测试分支所验证的真实行为与边界。
# 说明当前测试分支所验证的真实行为与边界。
class _CountState(TypedDict):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    count: Annotated[int, operator.add]


class _CloseableSaver(InMemorySaver):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""

    def __init__(self) -> None:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        super().__init__()
        self._closed = False
        self.writes_after_close: list[str] = []

    def close(self) -> None:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        self._closed = True

    async def aput(self, *args, **kwargs):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        if self._closed:
            self.writes_after_close.append("aput")
            raise RuntimeError("checkpointer is closed")
        return await super().aput(*args, **kwargs)

    async def aput_writes(self, *args, **kwargs):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        if self._closed:
            self.writes_after_close.append("aput_writes")
            raise RuntimeError("checkpointer is closed")
        return await super().aput_writes(*args, **kwargs)


@pytest.mark.asyncio
async def test_shutdown_cancels_and_awaits_inflight_run():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    rm = RunManager()
    record = await rm.create("t-drain")
    await rm.set_status(record.run_id, RunStatus.running)

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker() -> None:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        try:
            started.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    record.task = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(started.wait(), timeout=1.0)

        await rm.shutdown(timeout=5.0)

        assert record.task.done()
        assert cancelled.is_set()
        assert record.status == RunStatus.interrupted
    finally:
        if not record.task.done():
            record.task.cancel()
            with suppress(asyncio.CancelledError):
                await record.task


@pytest.mark.asyncio
async def test_shutdown_is_bounded_when_run_ignores_cancellation():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    rm = RunManager()
    record = await rm.create("t-stubborn")
    await rm.set_status(record.run_id, RunStatus.running)

    started = asyncio.Event()
    stop = asyncio.Event()

    async def stubborn() -> None:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        started.set()
        while not stop.is_set():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if stop.is_set():
                    raise
                # 说明当前测试分支所验证的真实行为与边界。

    record.task = asyncio.create_task(stubborn())
    try:
        await asyncio.wait_for(started.wait(), timeout=1.0)

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await rm.shutdown(timeout=0.3)
        elapsed = loop.time() - t0

        assert elapsed < 2.0, f"shutdown took {elapsed:.2f}s; drain is not bounded"
    finally:
        # 说明当前测试分支所验证的真实行为与边界。
        stop.set()
        record.task.cancel()
        with suppress(asyncio.CancelledError):
            await record.task


@pytest.mark.asyncio
async def test_shutdown_is_noop_without_inflight_runs():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    rm = RunManager()
    await rm.shutdown(timeout=1.0)
    # 说明当前测试分支所验证的真实行为与边界。
    record = await rm.create("t-done")
    await rm.set_status(record.run_id, RunStatus.success)
    await rm.shutdown(timeout=1.0)


@pytest.mark.asyncio
async def test_langgraph_runtime_drains_runs_before_closing_checkpointer(monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from fastapi import FastAPI

    from app.gateway.deps import langgraph_runtime

    events: list[str] = []

    @asynccontextmanager
    async def probe_checkpointer(_config):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        try:
            yield object()
        finally:
            events.append("checkpointer_closed")

    @asynccontextmanager
    async def fake_stream_bridge(_config):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        yield object()

    @asynccontextmanager
    async def fake_store(_config):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        yield object()

    async def fake_init_engine(_db):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        return None

    async def fake_close_engine():
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        return None

    async def spy_shutdown(self, *, timeout):  # noqa: ANN001
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        events.append("runs_drained")

    monkeypatch.setattr("deerflow.runtime.checkpointer.async_provider.make_checkpointer", probe_checkpointer)
    monkeypatch.setattr("deerflow.runtime.make_stream_bridge", fake_stream_bridge)
    monkeypatch.setattr("deerflow.runtime.make_store", fake_store)
    monkeypatch.setattr("deerflow.persistence.engine.init_engine_from_config", fake_init_engine)
    monkeypatch.setattr("deerflow.persistence.engine.close_engine", fake_close_engine)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: None)
    monkeypatch.setattr("deerflow.runtime.events.store.make_run_event_store", lambda _cfg: object())
    monkeypatch.setattr("deerflow.persistence.thread_meta.make_thread_store", lambda _sf, _store: object())
    monkeypatch.setattr(RunManager, "shutdown", spy_shutdown, raising=False)

    app = FastAPI()
    startup_config = SimpleNamespace(database=SimpleNamespace(backend="memory"), run_events=None)

    async with langgraph_runtime(app, startup_config):
        pass

    assert "runs_drained" in events, "langgraph_runtime never drained in-flight runs on shutdown"
    assert "checkpointer_closed" in events
    assert events.index("runs_drained") < events.index("checkpointer_closed"), f"runs must be drained before the checkpointer pool is closed; got order {events}"


@pytest.mark.asyncio
async def test_drain_flushes_real_graph_checkpoint_before_close():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from langgraph.graph import END, START, StateGraph

    async def slow(_state: _CountState) -> dict:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        await asyncio.sleep(0.1)
        return {"count": 1}

    saver = _CloseableSaver()
    builder = StateGraph(_CountState)
    for name in ("a", "b", "c"):
        builder.add_node(name, slow)
    builder.add_edge(START, "a")
    builder.add_edge("a", "b")
    builder.add_edge("b", "c")
    builder.add_edge("c", END)
    graph = builder.compile(checkpointer=saver)

    rm = RunManager()
    record = await rm.create("t-e2e")
    await rm.set_status(record.run_id, RunStatus.running)
    thread_cfg = {"configurable": {"thread_id": "t-e2e"}}

    started = asyncio.Event()

    async def run() -> None:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        started.set()
        async for _ in graph.astream({"count": 0}, config=thread_cfg):
            pass

    record.task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(started.wait(), timeout=1.0)

        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        # 说明当前测试分支所验证的真实行为与边界。
        async def _await_first_checkpoint() -> None:
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            while (await saver.aget_tuple(thread_cfg)) is None:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_await_first_checkpoint(), timeout=5.0)

        # 说明当前测试分支所验证的真实行为与边界。
        await rm.shutdown(timeout=5.0)
        # 说明当前测试分支所验证的真实行为与边界。
        saver.close()

        assert saver.writes_after_close == [], f"a checkpoint write raced a closed checkpointer: {saver.writes_after_close}"
        # 说明当前测试分支所验证的真实行为与边界。
        snapshot = await saver.aget_tuple(thread_cfg)
        assert snapshot is not None
    finally:
        if not record.task.done():
            record.task.cancel()
            with suppress(asyncio.CancelledError):
                await record.task


@pytest.mark.asyncio
async def test_shutdown_preserves_status_of_run_completed_during_drain():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    rm = RunManager(store=store)
    record = await rm.create("t-complete")
    await rm.set_status(record.run_id, RunStatus.running)

    async def worker() -> None:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # 说明当前测试分支所验证的真实行为与边界。
            # 说明当前测试分支所验证的真实行为与边界。
            # 说明当前测试分支所验证的真实行为与边界。
            pass
        await rm.set_status(record.run_id, RunStatus.success)

    record.task = asyncio.create_task(worker())
    try:
        await asyncio.sleep(0)  # 说明当前测试分支所验证的真实行为与边界。

        await rm.shutdown(timeout=5.0)

        assert record.status == RunStatus.success, f"shutdown overwrote in-memory status: {record.status}"
        persisted = await store.get(record.run_id)
        assert persisted is not None and persisted["status"] == "success", f"shutdown overwrote persisted status: {persisted}"
    finally:
        if not record.task.done():
            record.task.cancel()
            with suppress(asyncio.CancelledError):
                await record.task


@pytest.mark.asyncio
async def test_shutdown_surfaces_failed_interrupted_persist(caplog):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    import logging

    from deerflow.runtime.runs.store.memory import MemoryRunStore

    class _FailingStore(MemoryRunStore):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        async def update_status(self, *args, **kwargs):
            """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
            raise RuntimeError("store unavailable")

    rm = RunManager(store=_FailingStore())
    record = await rm.create("t-failpersist")
    record.status = RunStatus.running  # 说明当前测试分支所验证的真实行为与边界。

    started = asyncio.Event()

    async def worker() -> None:
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        started.set()
        await asyncio.Event().wait()  # 说明当前测试分支所验证的真实行为与边界。

    record.task = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(started.wait(), timeout=1.0)
        with caplog.at_level(logging.WARNING, logger="deerflow.runtime.runs.manager"):
            await rm.shutdown(timeout=5.0)
        assert "Could not persist interrupted status for run" in caplog.text, caplog.text
    finally:
        if not record.task.done():
            record.task.cancel()
            with suppress(asyncio.CancelledError):
                await record.task
