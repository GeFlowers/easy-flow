'''定义事件流数据结构与桥接器的结构化类型契约。'''

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StreamEvent:
    '''表示可通过服务端事件推送传递、并支持断线续读的单条运行事件。'''

    id: str
    event: str
    data: Any


HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)


class StreamBridge(Protocol):
    '''描述运行事件生产者、订阅者和资源清理所需的方法。'''

    supports_cross_process: bool

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        '''发布一条运行事件，供当前运行的订阅者读取。'''
        ...

    async def publish_end(self, run_id: str) -> None:
        '''发布终止标记，通知订阅者该运行不会再产生事件。'''
        ...

    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        '''按事件 ID 续读运行流，并在等待期间按间隔发出心跳标记。'''
        ...

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        '''释放运行事件流资源；可延迟执行以供迟到的订阅者读取终止标记。'''
        ...

    async def close(self) -> None:
        '''关闭桥接器拥有的连接池或其他共享资源。'''
        ...
