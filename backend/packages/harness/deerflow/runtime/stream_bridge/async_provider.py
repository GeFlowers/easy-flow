'''

Async stream bridge factory.

Provides an **async context manager** aligned with
:func:`deerflow.runtime.checkpointer.async_provider.make_checkpointer`.

Usage (e.g. FastAPI lifespan)::

    from deerflow.agents.stream_bridge import make_stream_bridge

    async with make_stream_bridge() as bridge:
        app.state.stream_bridge = bridge
'''

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator

from deerflow.config.app_config import AppConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig, get_stream_bridge_config

from .base import StreamBridge

logger = logging.getLogger(__name__)

_ENV_REDIS_URL = "DEER_FLOW_STREAM_BRIDGE_REDIS_URL"


def _resolve_config(app_config: AppConfig | None) -> StreamBridgeConfig | None:
    '''优先从显式应用配置读取桥接设置，并兼容只设置专用环境变量的启动方式。'''
    if app_config is None:
        config = get_stream_bridge_config()
    else:
        config = app_config.stream_bridge

    if config is None:
        redis_url = os.getenv(_ENV_REDIS_URL)
        if redis_url:
            return StreamBridgeConfig(redis_url=redis_url)
    return config


def _resolve_redis_url(config: StreamBridgeConfig) -> str:
    '''按配置项、专用环境变量、通用环境变量的顺序解析 Redis 地址。'''
    return config.redis_url or os.getenv(_ENV_REDIS_URL) or os.getenv("REDIS_URL") or "redis://localhost:6379/0"


@contextlib.asynccontextmanager
async def make_stream_bridge(app_config: AppConfig | None = None) -> AsyncIterator[StreamBridge]:
    '''创建 Redis 事件桥接器，并在上下文退出时关闭其连接。'''
    config = _resolve_config(app_config)

    from deerflow.runtime.stream_bridge.redis import RedisStreamBridge

    config = config or StreamBridgeConfig()
    bridge = RedisStreamBridge(
        redis_url=_resolve_redis_url(config),
        queue_maxsize=config.queue_maxsize,
        max_connections=config.max_connections,
        stream_ttl_seconds=config.stream_ttl_seconds,
    )
    logger.info(
        "Stream bridge initialized: redis (queue_maxsize=%d, max_connections=%s, stream_ttl_seconds=%d)",
        config.queue_maxsize,
        config.max_connections,
        config.stream_ttl_seconds,
    )
    try:
        yield bridge
    finally:
        await bridge.close()
