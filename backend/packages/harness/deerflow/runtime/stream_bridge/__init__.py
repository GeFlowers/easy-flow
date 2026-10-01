'''

Stream bridge — decouples agent workers from SSE endpoints.

A ``StreamBridge`` sits between the background task that runs an agent
(producer) and the HTTP endpoint that pushes Server-Sent Events to
the client (consumer). The protocol is structural; the Gateway currently uses
the Redis Streams implementation.
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
