"""提供配置、stream、bridge、配置相关功能。"""

from typing import Literal

from pydantic import BaseModel, Field

StreamBridgeType = Literal["memory", "redis"]


class StreamBridgeConfig(BaseModel):
    """\u6267\u884c StreamBridgeConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    type: StreamBridgeType = Field(
        default="memory",
        description="Stream bridge backend type. 'memory' uses an in-process event log (single-process only). 'redis' uses Redis Streams for multi-worker Docker deployments.",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for the redis stream bridge type. If omitted, DEER_FLOW_STREAM_BRIDGE_REDIS_URL, REDIS_URL, or redis://localhost:6379/0 is used.",
    )
    queue_maxsize: int = Field(
        default=256,
        description="Maximum number of events retained per run (memory bridge queue size / redis stream MAXLEN).",
    )
    max_connections: int | None = Field(
        default=None,
        description=(
            "Max Redis connections in the pool for the redis stream bridge. Each live SSE "
            "client holds one connection blocked in XREAD ... BLOCK for up to heartbeat_interval "
            "(15s), so hundreds of concurrent clients open hundreds of connections. Leave unset "
            "for redis-py's default (effectively unbounded), or set a ceiling sized for peak "
            "concurrent SSE clients. Only applies to the redis bridge."
        ),
    )
    stream_ttl_seconds: int = Field(
        default=86400,
        ge=0,
        description=(
            "Rolling Redis stream key TTL in seconds. The redis bridge refreshes this TTL after "
            "each publish and publish_end so retained SSE replay buffers are eventually reclaimed "
            "even if cleanup never runs. Set to 0 to disable. Only applies to the redis bridge."
        ),
    )
    recovered_stream_cleanup_delay_seconds: float = Field(
        default=60.0,
        ge=0,
        description=("Seconds to wait after publishing an END marker for a recovered orphaned run before deleting the stream key. Gives reconnecting SSE clients time to drain the end signal. Only applies to the redis bridge."),
    )


# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
_stream_bridge_config: StreamBridgeConfig | None = None


def get_stream_bridge_config() -> StreamBridgeConfig | None:
    """\u6267\u884c get_stream_bridge_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return _stream_bridge_config


def set_stream_bridge_config(config: StreamBridgeConfig | None) -> None:
    """\u6267\u884c set_stream_bridge_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _stream_bridge_config
    _stream_bridge_config = config


def load_stream_bridge_config_from_dict(config_dict: dict | None) -> None:
    """\u6267\u884c load_stream_bridge_config_from_dict \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _stream_bridge_config
    if config_dict is None:
        _stream_bridge_config = None
        return
    _stream_bridge_config = StreamBridgeConfig(**config_dict)
