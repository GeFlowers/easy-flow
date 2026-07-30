'未说明'

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from deerflow.runtime import RunManager, RunRecord, RunStatus
from deerflow.runtime.runs.schemas import DisconnectMode
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

THREAD_ID = "thread-wait-3265"


@dataclass
class _FakeRequest:
    '未说明'

    disconnect_after: int = 10**9  # effectively "never" by default
    headers: dict[str, str] = field(default_factory=dict)
    _polls: int = 0

    async def is_disconnected(self) -> bool:
        '未说明'
        self._polls += 1
        return self._polls > self.disconnect_after


class _MissingStreamBridge:
    '未说明'

    supports_cross_process = True

    def __init__(self) -> None:
        '未说明'
        self.subscribed = False

    async def publish(self, run_id, event, data):
        '未说明'
        return None

    async def publish_end(self, run_id):
        '未说明'
        return None

    async def stream_exists(self, run_id: str) -> bool:
        """处理流相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return False

    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
        '未说明'
        self.subscribed = True
        raise AssertionError("terminal missing streams should end before subscribing")

    async def cleanup(self, run_id, *, delay=0):
        '未说明'
        return None


async def _create_running_record(mgr: RunManager, *, on_disconnect: DisconnectMode) -> Any:
    '未说明'
    record = await mgr.create_or_reject(
        THREAD_ID,
        assistant_id=None,
        on_disconnect=on_disconnect,
    )
    await mgr.set_status(record.run_id, RunStatus.running)
    return record


# ---------------------------------------------------------------------------
# Helper-level unit tests
# ---------------------------------------------------------------------------


class TestWaitForRunCompletion:
    '未说明'
    def test_returns_when_run_publishes_end(self) -> None:
        '未说明'
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.cancel)
            request = _FakeRequest()

            async def finish_soon() -> None:
                '未说明'
                await asyncio.sleep(0)
                await bridge.publish(record.run_id, "values", {"messages": []})
                await mgr.set_status(record.run_id, RunStatus.success)
                await bridge.publish_end(record.run_id)

            asyncio.create_task(finish_soon())
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )
            assert completed is True
            assert record.status == RunStatus.success

        asyncio.run(run())

    def test_cancels_run_on_disconnect_when_cancel_mode(self) -> None:
        '未说明'
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.cancel)
            # Attach a real (idle) task so cancel() actually has something to cancel.
            sleeper = asyncio.create_task(asyncio.sleep(30))
            record.task = sleeper
            request = _FakeRequest(disconnect_after=0)  # disconnected on first poll

            async def publish_until_cancel() -> None:
                # Emit one event so subscribe wakes up immediately; helper polls
                # is_disconnected after each yield.
                '未说明'
                await asyncio.sleep(0)
                await bridge.publish(record.run_id, "values", {"step": 1})

            asyncio.create_task(publish_until_cancel())
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )

            assert completed is False
            assert record.status == RunStatus.interrupted
            # Drain the cancelled sleeper so it does not linger past the test.
            try:
                await asyncio.wait_for(sleeper, timeout=1.0)
            except asyncio.CancelledError:
                pass
            assert sleeper.done()

        asyncio.run(run())

    def test_does_not_cancel_when_continue_mode(self) -> None:
        '未说明'
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.continue_)
            sleeper = asyncio.create_task(asyncio.sleep(30))
            record.task = sleeper
            request = _FakeRequest(disconnect_after=0)

            async def publish_then_end() -> None:
                '未说明'
                await asyncio.sleep(0)
                await bridge.publish(record.run_id, "values", {"step": 1})

            asyncio.create_task(publish_then_end())
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )

            # Disconnected before END — helper still reports incomplete so the
            # caller skips checkpoint serialization, but the run keeps going.
            assert completed is False
            assert record.status == RunStatus.running
            sleeper.cancel()

        asyncio.run(run())

    def test_no_cancel_when_run_already_finished(self) -> None:
        '未说明'
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.cancel)
            # Publish END before subscribe — helper should see ended=True first
            # poll and return without ever observing the "disconnect".
            await mgr.set_status(record.run_id, RunStatus.success)
            await bridge.publish_end(record.run_id)
            request = _FakeRequest(disconnect_after=0)

            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )

            assert completed is True
            assert record.status == RunStatus.success

        asyncio.run(run())

    def test_terminal_missing_stream_returns_complete(self) -> None:
        '未说明'
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            mgr = RunManager()
            bridge = _MissingStreamBridge()
            record = RunRecord(
                run_id="terminal-missing-run",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.success,
                on_disconnect=DisconnectMode.cancel,
                store_only=True,
            )
            request = _FakeRequest()

            completed = await wait_for_run_completion(bridge, record, request, mgr)

            assert completed is True
            assert bridge.subscribed is False

        asyncio.run(run())

    def test_sse_consumer_terminal_missing_stream_yields_end(self) -> None:
        '未说明'
        from app.gateway.services import sse_consumer

        async def run() -> None:
            """处理运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            mgr = RunManager()
            bridge = _MissingStreamBridge()
            record = RunRecord(
                run_id="terminal-missing-run",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.success,
                on_disconnect=DisconnectMode.cancel,
                store_only=True,
            )
            request = _FakeRequest()

            frames = [frame async for frame in sse_consumer(bridge, record, request, mgr)]

            assert frames == ["event: end\ndata: null\n\n"]
            assert bridge.subscribed is False

        asyncio.run(run())
