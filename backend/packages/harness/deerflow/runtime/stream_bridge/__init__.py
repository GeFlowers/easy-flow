"""

Stream bridge — decouples agent workers from SSE endpoints.

A ``StreamBridge`` sits between the background task that runs an agent
(producer) and the HTTP endpoint that pushes Server-Sent Events to
the client (consumer). The protocol is structural; the Gateway currently uses
the Redis Streams implementation.
"""

from .async_provider import make_stream_bridge
from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent
# NOTE: ``RedisStreamBridge`` is intentionally NOT imported here. ``redis`` is an
# optional extra, and this package is pulled in transitively by ``deerflow.runtime``
# at process startup. Importing ``.redis`` eagerly would import ``redis.asyncio``
# for consumers that only use the harness API. It is imported lazily inside
# ``make_stream_bridge`` when the Gateway initializes its event bridge. Import it
# directly from ``deerflow.runtime.stream_bridge.redis`` if you need the class.

__all__ = [
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "StreamBridge",
    "StreamEvent",
    "make_stream_bridge",
]
