"""定义 Redis 事件流桥接器的运行参数和当前配置缓存。"""

from pydantic import BaseModel, Field


class StreamBridgeConfig(BaseModel):
    """配置 Redis 事件流连接、保留长度及清理时机。"""

    redis_url: str | None = Field(
        default=None,
        description="Redis 连接地址；未设置时依次读取 DEER_FLOW_STREAM_BRIDGE_REDIS_URL、REDIS_URL，最后使用本机默认地址。",
    )
    queue_maxsize: int = Field(
        default=256,
        description="每次运行在 Redis Stream 中最多保留的事件数量。",
    )
    max_connections: int | None = Field(
        default=None,
        description=(
            "Redis 连接池的最大连接数。每个活动 SSE 客户端在 XREAD 阻塞等待期间占用一个连接，"
            "最长等待一个心跳周期（15 秒）。未设置时采用 redis-py 默认值，也可根据 SSE 并发峰值设置上限。"
        ),
    )
    stream_ttl_seconds: int = Field(
        default=86400,
        ge=0,
        description=(
            "Redis 事件流键的滚动过期秒数。每次发布事件或结束标记后刷新过期时间，"
            "即使主动清理未运行，旧事件缓冲区最终也会回收；设为 0 可禁用。"
        ),
    )
    recovered_stream_cleanup_delay_seconds: float = Field(
        default=60.0,
        ge=0,
        description=("等待恢复的孤儿运行发布结束标记后再删除流键的秒数，以便重连的 SSE 客户端读取终止事件。"),
    )


_stream_bridge_config: StreamBridgeConfig | None = None


def get_stream_bridge_config() -> StreamBridgeConfig | None:
    """返回当前缓存的事件流桥接配置。"""
    return _stream_bridge_config


def set_stream_bridge_config(config: StreamBridgeConfig | None) -> None:
    """替换缓存的事件流配置，供配置重载流程更新使用。"""
    global _stream_bridge_config
    _stream_bridge_config = config


def load_stream_bridge_config_from_dict(config_dict: dict | None) -> None:
    """从配置字典构建事件流配置；未提供配置时清空缓存。"""
    global _stream_bridge_config
    if config_dict is None:
        _stream_bridge_config = None
        return
    _stream_bridge_config = StreamBridgeConfig(**config_dict)
