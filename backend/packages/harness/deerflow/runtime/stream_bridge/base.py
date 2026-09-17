"""定义 base 模块提供的职责与可复用接口。

Abstract stream bridge protocol.

StreamBridge decouples agent workers (producers) from SSE endpoints
(consumers), aligning with LangGraph Platform's Queue + StreamManager
architecture.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StreamEvent:
    """封装 StreamEvent 的状态、协作关系与公开操作。

    Single stream event.

        Attributes:
            id: Monotonically increasing event ID (used as SSE ``id:`` field,
                supports ``Last-Event-ID`` reconnection).
            event: SSE event name, e.g. ``"metadata"``, ``"updates"``,
                ``"events"``, ``"error"``, ``"end"``.
            data: JSON-serialisable payload.
    """

    id: str
    event: str
    data: Any


HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)


class StreamBridge(abc.ABC):
    """封装 StreamBridge 的状态、协作关系与公开操作。

    Abstract base for stream bridges."""

    supports_cross_process: bool = False

    @abc.abstractmethod
    async def publish(self, run_id: str, event: str, data: Any) -> None:
        """执行 publish 的明确职责，并返回与调用约定一致的结果。

        Enqueue a single event for *run_id* (producer side)."""

    @abc.abstractmethod
    async def publish_end(self, run_id: str) -> None:
        """执行 publish_end 的明确职责，并返回与调用约定一致的结果。

        Signal that no more events will be produced for *run_id*."""

    @abc.abstractmethod
    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        """执行 subscribe 的明确职责，并返回与调用约定一致的结果。

        Async iterator that yields events for *run_id* (consumer side).

                Yields :data:`HEARTBEAT_SENTINEL` when no event arrives within
                *heartbeat_interval* seconds.  Yields :data:`END_SENTINEL` once
                the producer calls :meth:`publish_end`.
        """

    @abc.abstractmethod
    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """执行 cleanup 的明确职责，并返回与调用约定一致的结果。

        Release resources associated with *run_id*.

                If *delay* > 0 the implementation should wait before releasing,
                giving late subscribers a chance to drain remaining events.
        """

    async def close(self) -> None:
        """执行 close 的明确职责，并返回与调用约定一致的结果。

        Release backend resources.  Default is a no-op."""
