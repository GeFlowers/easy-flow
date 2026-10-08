'''

事件流桥接器，用于解耦智能体工作器与服务端事件推送接口。

``StreamBridge`` 连接执行智能体的后台任务（生产方）与向客户端推送事件的
网络接口（消费方）。该协议采用结构化类型，网关当前使用 Redis Streams 实现。
'''

from .async_provider import make_stream_bridge
from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent

__all__ = [
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "StreamBridge",
    "StreamEvent",
    "make_stream_bridge",
]
