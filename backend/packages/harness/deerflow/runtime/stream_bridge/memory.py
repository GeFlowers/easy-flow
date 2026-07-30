'定义 memory 模块提供的职责与可复用接口。\n\nIn-memory stream bridge backed by an in-process event log.'

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent

logger = logging.getLogger(__name__)


@dataclass
class _RunStream:
    '封装 _RunStream 的状态、协作关系与公开操作'
    events: list[StreamEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    ended: bool = False
    start_offset: int = 0


class MemoryStreamBridge(StreamBridge):
    '封装 MemoryStreamBridge 的状态、协作关系与公开操作。\n\nPer-run in-memory event log implementation.\n\n    Events are retained for a bounded time window per run so late subscribers\n    and reconnecting clients can replay buffered events from ``Last-Event-ID``.\n    '

    def __init__(self, *, queue_maxsize: int = 256) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        self._maxsize = queue_maxsize
        self._streams: dict[str, _RunStream] = {}
        self._counters: dict[str, int] = {}

    # -- helpers ---------------------------------------------------------------

    def _get_or_create_stream(self, run_id: str) -> _RunStream:
        '执行 _get_or_create_stream 的明确职责，并返回与调用约定一致的结果'
        if run_id not in self._streams:
            self._streams[run_id] = _RunStream()
            self._counters[run_id] = 0
        return self._streams[run_id]

    def _next_id(self, run_id: str) -> str:
        '执行 _next_id 的明确职责，并返回与调用约定一致的结果'
        self._counters[run_id] = self._counters.get(run_id, 0) + 1
        ts = int(time.time() * 1000)
        seq = self._counters[run_id] - 1
        return f"{ts}-{seq}"

    @staticmethod
    def _parse_event_seq(event_id: str) -> int | None:
        "执行 _parse_event_seq 的明确职责，并返回与调用约定一致的结果。\n\nExtract the per-run sequence number from a ``{ts}-{seq}`` event id.\n\n        ``seq`` (assigned by :meth:`_next_id`) increases by one per published\n        event, so it equals the event's absolute offset within the run. Returns\n        ``None`` for ids that do not match the expected format.\n        "
        _, sep, seq_text = event_id.rpartition("-")
        if not sep:
            return None
        try:
            return int(seq_text)
        except ValueError:
            return None

    def _resolve_start_offset(self, stream: _RunStream, last_event_id: str | None) -> int:
        '执行 _resolve_start_offset 的明确职责，并返回与调用约定一致的结果'
        if last_event_id is None:
            return stream.start_offset

        # Event ids embed a per-run, monotonically increasing ``seq`` that equals
        # the event's absolute offset, so locate the event by arithmetic in O(1)
        # rather than scanning the retained buffer. The id is verified at the
        # computed index, so a stale/evicted/foreign/malformed id still falls back
        # to replay-from-earliest — identical to the previous linear scan.
        seq = self._parse_event_seq(last_event_id)
        if seq is not None:
            local_index = seq - stream.start_offset
            if 0 <= local_index < len(stream.events) and stream.events[local_index].id == last_event_id:
                return stream.start_offset + local_index + 1

        if stream.events:
            logger.warning(
                "last_event_id=%s not found in retained buffer; replaying from earliest retained event",
                last_event_id,
            )
        return stream.start_offset

    async def stream_exists(self, run_id: str) -> bool:
        '持续产出流式结果并传递终止状态，并遵守 stream_exists 所表达的接口约束。\n\nReturn whether the in-process event log still has data for *run_id*.'
        return run_id in self._streams

    # -- StreamBridge API ------------------------------------------------------

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        '执行 publish 的明确职责，并返回与调用约定一致的结果'
        stream = self._get_or_create_stream(run_id)
        entry = StreamEvent(id=self._next_id(run_id), event=event, data=data)
        async with stream.condition:
            stream.events.append(entry)
            if len(stream.events) > self._maxsize:
                overflow = len(stream.events) - self._maxsize
                del stream.events[:overflow]
                stream.start_offset += overflow
            stream.condition.notify_all()

    async def publish_end(self, run_id: str) -> None:
        '执行 publish_end 的明确职责，并返回与调用约定一致的结果'
        stream = self._get_or_create_stream(run_id)
        async with stream.condition:
            stream.ended = True
            stream.condition.notify_all()

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        '执行 subscribe 的明确职责，并返回与调用约定一致的结果'
        stream = self._get_or_create_stream(run_id)
        async with stream.condition:
            next_offset = self._resolve_start_offset(stream, last_event_id)

        while True:
            async with stream.condition:
                if next_offset < stream.start_offset:
                    logger.warning(
                        "subscriber for run %s fell behind retained buffer; resuming from offset %s",
                        run_id,
                        stream.start_offset,
                    )
                    next_offset = stream.start_offset

                local_index = next_offset - stream.start_offset
                if 0 <= local_index < len(stream.events):
                    entry = stream.events[local_index]
                    next_offset += 1
                elif stream.ended:
                    entry = END_SENTINEL
                else:
                    try:
                        await asyncio.wait_for(stream.condition.wait(), timeout=heartbeat_interval)
                    except TimeoutError:
                        entry = HEARTBEAT_SENTINEL
                    else:
                        continue

            if entry is END_SENTINEL:
                yield END_SENTINEL
                return
            yield entry

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        '执行 cleanup 的明确职责，并返回与调用约定一致的结果'
        if delay > 0:
            await asyncio.sleep(delay)
        self._streams.pop(run_id, None)
        self._counters.pop(run_id, None)

    async def close(self) -> None:
        '执行 close 的明确职责，并返回与调用约定一致的结果'
        self._streams.clear()
        self._counters.clear()
