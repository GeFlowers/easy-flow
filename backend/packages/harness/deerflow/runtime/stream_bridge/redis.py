"""通过 Redis Streams 在 Gateway 进程间转发并重放运行事件。"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any

try:
    from redis.asyncio import Redis
    from redis.exceptions import RedisError, ResponseError
except ImportError:  # pragma: no cover - only hit when the optional extra is missing
    # Redis remains an optional package extra and is imported only when the
    # Gateway initializes its configured event bridge.
    raise ImportError(
        "The Redis stream bridge is configured but the redis package is not installed.\n"
        "Install it with:\n"
        "    cd backend && uv sync --all-packages --extra redis\n"
        "The supported Docker image includes the redis extra.\n"
        "Configure the Redis URL through stream_bridge.redis_url or an environment variable."
    ) from None

from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamEvent

logger = logging.getLogger(__name__)

_KIND_EVENT = "event"
_KIND_END = "end"
_REDIS_STREAM_ID_RE = re.compile(r"\d+(-\d+)?")

# Batch size for ``XREAD``. Reading more than one entry per round-trip collapses
# a large ``Last-Event-ID`` replay into far fewer calls; live tailing still
# yields each event as it arrives because the consume loop returns mid-batch on
# the end marker.
_XREAD_COUNT = 64

# Maximum consecutive transient Redis errors (``ConnectionError``,
# ``TimeoutError``, etc.) tolerated during ``subscribe`` before the error
# propagates to the caller.  Brief blips are retried with exponential backoff
# capped at ``heartbeat_interval``.
_MAX_SUBSCRIBE_RETRIES = 3


class RedisStreamBridge:
    """将每个运行的事件写入 Redis Stream，支持多进程订阅和断线续读。"""

    supports_cross_process = True

    def __init__(
        self,
        *,
        redis_url: str,
        queue_maxsize: int = 256,
        key_prefix: str = "deerflow:stream_bridge",
        max_connections: int | None = None,
        stream_ttl_seconds: int | None = 86400,
        client: Redis | None = None,
    ) -> None:
        """初始化事件流参数，并复用注入客户端或创建自有 Redis 连接池。"""
        self._redis_url = redis_url
        self._maxsize = max(1, queue_maxsize)
        self._key_prefix = key_prefix.rstrip(":")
        if stream_ttl_seconds is not None and stream_ttl_seconds > 0:
            self._stream_ttl_seconds = stream_ttl_seconds
        else:
            self._stream_ttl_seconds = None
        # Each live SSE subscriber holds one pooled connection blocked in
        # ``XREAD ... BLOCK`` for up to ``heartbeat_interval``. ``max_connections``
        # caps that pool; ``None`` keeps redis-py's effectively-unbounded default.
        self._redis = client if client is not None else Redis.from_url(redis_url, decode_responses=True, max_connections=max_connections)
        self._owns_client = client is None

    def _stream_key(self, run_id: str) -> str:
        """为运行 ID 拼出对应的 Redis Stream 键。"""
        return f"{self._key_prefix}:{run_id}"

    async def _xadd_retained(self, key: str, fields: dict[str, str], *, maxlen: int) -> None:
        """追加事件并在启用保留期限时原子刷新流键 TTL。"""
        if self._stream_ttl_seconds is None:
            await self._redis.xadd(
                key,
                fields,
                maxlen=maxlen,
                approximate=False,
            )
            return

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xadd(
                key,
                fields,
                maxlen=maxlen,
                approximate=False,
            )
            pipe.expire(key, self._stream_ttl_seconds)
            await pipe.execute()

    @staticmethod
    def _decode(value: Any) -> str:
        """把 Redis 返回的字节或标量统一转换为字符串。"""
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    @classmethod
    def _normalise_fields(cls, fields: Mapping[Any, Any]) -> dict[str, str]:
        """规范化 Redis 哈希字段的键和值类型。"""
        return {cls._decode(key): cls._decode(value) for key, value in fields.items()}

    @staticmethod
    def _encode_data(data: Any) -> str:
        """将事件数据编码为紧凑的 UTF-8 JSON 文本。"""
        return json.dumps(data, default=str, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_data(raw: str | None) -> Any:
        """解析事件 JSON；遇到旧格式或损坏内容时保留原文。"""
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Redis stream bridge received non-JSON event data")
            return raw

    def _entry_from_redis(self, event_id: str, fields: Mapping[Any, Any]) -> StreamEvent:
        """把 Redis Stream 条目转换为运行时事件或终止标记。"""
        payload = self._normalise_fields(fields)
        kind = payload.get("kind", _KIND_EVENT)
        if kind == _KIND_END:
            return END_SENTINEL
        return StreamEvent(
            id=event_id,
            event=payload.get("event", "message"),
            data=self._decode_data(payload.get("data")),
        )

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        """保存一条运行事件，并按配置限制可重放的事件数量。"""
        key = self._stream_key(run_id)
        await self._xadd_retained(
            key,
            {
                "kind": _KIND_EVENT,
                "event": event,
                "data": self._encode_data(data),
            },
            maxlen=self._maxsize,
        )

    async def publish_end(self, run_id: str) -> None:
        """追加运行终止标记，并额外为该标记预留一个保留位置。"""
        # Keep the configured number of data events plus the internal end marker.
        key = self._stream_key(run_id)
        await self._xadd_retained(
            key,
            {"kind": _KIND_END},
            maxlen=self._maxsize + 1,
        )

    async def stream_exists(self, run_id: str) -> bool:
        """检查 Redis 中是否仍保留该运行的事件流。"""
        return bool(await self._redis.exists(self._stream_key(run_id)))

    async def _resolve_start_stream_id(self, key: str, last_event_id: str | None) -> str:
        """校验续读游标，并决定首次读取或非法游标的安全起点。"""
        if last_event_id is None:
            return "0-0"
        if _REDIS_STREAM_ID_RE.fullmatch(last_event_id):
            return last_event_id
        entries = await self._redis.xrevrange(key, count=1)
        if not entries:
            return "0-0"
        event_id, fields = entries[0]
        payload = self._normalise_fields(fields)
        if payload.get("kind") == _KIND_END:
            return "0-0"
        return self._decode(event_id)

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        """从给定事件游标持续读取事件，并在空闲或短暂故障时维护连接。"""
        key = self._stream_key(run_id)
        stream_id = await self._resolve_start_stream_id(key, last_event_id)
        block_ms = max(1, int(heartbeat_interval * 1000)) if heartbeat_interval > 0 else 1
        consecutive_errors = 0

        while True:
            try:
                response = await self._redis.xread({key: stream_id}, count=_XREAD_COUNT, block=block_ms)
            except ResponseError:
                # Last-Event-ID is client-controlled and validated before XREAD.
                # If Redis still rejects the id, fail instead of resetting to
                # 0-0, which would replay the whole retained buffer on reconnect.
                logger.warning(
                    "Redis rejected stream id %r for stream bridge subscription",
                    stream_id,
                    exc_info=True,
                )
                raise
            except RedisError:
                consecutive_errors += 1
                if consecutive_errors > _MAX_SUBSCRIBE_RETRIES:
                    raise
                delay = min(2**consecutive_errors, heartbeat_interval)
                logger.warning(
                    "Transient Redis error in stream bridge subscriber (retry %d/%d); backing off %.1fs",
                    consecutive_errors,
                    _MAX_SUBSCRIBE_RETRIES,
                    delay,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
                continue
            else:
                consecutive_errors = 0

            if not response:
                yield HEARTBEAT_SENTINEL
                continue

            for _stream_name, entries in response:
                for event_id, fields in entries:
                    event_id = self._decode(event_id)
                    stream_id = event_id
                    entry = self._entry_from_redis(event_id, fields)
                    if entry is END_SENTINEL:
                        yield END_SENTINEL
                        return
                    yield entry

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """可选等待订阅者读取终止标记后，删除该运行的 Redis Stream。"""
        if delay > 0:
            await asyncio.sleep(delay)
        await self._redis.delete(self._stream_key(run_id))

    async def close(self) -> None:
        """只关闭由当前桥接器创建的 Redis 客户端。"""
        if not self._owns_client:
            return
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
