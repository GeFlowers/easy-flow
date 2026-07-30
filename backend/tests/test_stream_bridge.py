'未说明'

import asyncio
import os
import re
import uuid
from collections import defaultdict

import anyio
import pytest

from deerflow.config.stream_bridge_config import StreamBridgeConfig, set_stream_bridge_config
from deerflow.runtime import END_SENTINEL, HEARTBEAT_SENTINEL, MemoryStreamBridge, make_stream_bridge

# RedisStreamBridge is no longer re-exported from deerflow.runtime (redis is an
# optional extra; see the NOTE in runtime/stream_bridge/__init__.py). Import it
# directly from the submodule.
from deerflow.runtime.stream_bridge.redis import RedisStreamBridge


def _stream_id_gt(left: str, right: str) -> bool:
    '未说明'
    left_ms, left_seq = left.split("-", 1)
    right_ms, right_seq = right.split("-", 1)
    return (int(left_ms), int(left_seq)) > (int(right_ms), int(right_seq))


class _FakeRedis:
    '未说明'
    def __init__(self) -> None:
        '未说明'
        self.streams = defaultdict(list)
        self.conditions = defaultdict(asyncio.Condition)
        self.counters = defaultdict(int)
        self.deleted = []
        self.expirations = []
        self.closed = False

    async def xadd(self, name, fields, maxlen=None, approximate=True):
        '未说明'
        self.counters[name] += 1
        event_id = f"{self.counters[name]}-0"
        async with self.conditions[name]:
            self.streams[name].append((event_id, dict(fields)))
            if maxlen is not None and len(self.streams[name]) > maxlen:
                del self.streams[name][: len(self.streams[name]) - maxlen]
            self.conditions[name].notify_all()
        return event_id

    async def xread(self, streams, count=None, block=None):
        '未说明'
        [(name, last_id)] = list(streams.items())
        timeout = None if block is None else block / 1000
        while True:
            async with self.conditions[name]:
                entries = [(event_id, fields) for event_id, fields in self.streams.get(name, []) if _stream_id_gt(event_id, last_id)]
                if entries:
                    return [(name, entries[:count] if count is not None else entries)]
                if timeout is None:
                    return []
                try:
                    await asyncio.wait_for(self.conditions[name].wait(), timeout=timeout)
                except TimeoutError:
                    return []

    async def xrevrange(self, name, max="+", min="-", count=None):
        '未说明'
        entries = list(reversed(self.streams.get(name, [])))
        return entries[:count] if count is not None else entries

    async def delete(self, name):
        '未说明'
        self.deleted.append(name)
        self.streams.pop(name, None)
        return 1

    async def exists(self, name):
        '未说明'
        return 1 if name in self.streams else 0

    async def expire(self, name, seconds):
        '未说明'
        self.expirations.append((name, seconds))
        return True

    def pipeline(self, *, transaction=True):
        '未说明'
        return _FakeRedisPipeline(self)

    async def aclose(self):
        '未说明'
        self.closed = True


class _FakeRedisPipeline:
    '未说明'
    def __init__(self, redis: _FakeRedis) -> None:
        '未说明'
        self.redis = redis
        self.ops = []

    async def __aenter__(self):
        '未说明'
        return self

    async def __aexit__(self, exc_type, exc, tb):
        '未说明'
        return None

    def xadd(self, name, fields, maxlen=None, approximate=True):
        '未说明'
        self.ops.append(("xadd", name, fields, maxlen, approximate))
        return self

    def expire(self, name, seconds):
        '未说明'
        self.ops.append(("expire", name, seconds))
        return self

    async def execute(self):
        '未说明'
        results = []
        for op in self.ops:
            if op[0] == "xadd":
                _, name, fields, maxlen, approximate = op
                results.append(await self.redis.xadd(name, fields, maxlen=maxlen, approximate=approximate))
            elif op[0] == "expire":
                _, name, seconds = op
                results.append(await self.redis.expire(name, seconds))
        return results


# ---------------------------------------------------------------------------
# Unit tests for MemoryStreamBridge
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge() -> MemoryStreamBridge:
    '未说明'
    return MemoryStreamBridge(queue_maxsize=256)


@pytest.mark.anyio
async def test_publish_subscribe(bridge: MemoryStreamBridge):
    '未说明'
    run_id = "run-1"

    await bridge.publish(run_id, "metadata", {"run_id": run_id})
    await bridge.publish(run_id, "values", {"messages": []})
    await bridge.publish(run_id, "updates", {"step": 1})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(received) == 4
    assert received[0].event == "metadata"
    assert received[1].event == "values"
    assert received[2].event == "updates"
    assert received[3] is END_SENTINEL


@pytest.mark.anyio
async def test_heartbeat(bridge: MemoryStreamBridge):
    '未说明'
    run_id = "run-heartbeat"
    bridge._get_or_create_stream(run_id)  # ensure stream exists

    received = []

    async def consumer():
        '未说明'
        async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
            received.append(entry)
            if entry is HEARTBEAT_SENTINEL:
                break

    await asyncio.wait_for(consumer(), timeout=2.0)
    assert len(received) == 1
    assert received[0] is HEARTBEAT_SENTINEL


@pytest.mark.anyio
async def test_cleanup(bridge: MemoryStreamBridge):
    '未说明'
    run_id = "run-cleanup"
    await bridge.publish(run_id, "test", {})
    assert run_id in bridge._streams

    await bridge.cleanup(run_id)
    assert run_id not in bridge._streams
    assert run_id not in bridge._counters


@pytest.mark.anyio
async def test_stream_exists_reports_cleanup(bridge: MemoryStreamBridge):
    '未说明'
    run_id = "run-post-cleanup"
    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish_end(run_id)

    assert await bridge.stream_exists(run_id) is True
    await bridge.cleanup(run_id)
    assert await bridge.stream_exists(run_id) is False


@pytest.mark.anyio
async def test_history_is_bounded():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=1)
    run_id = "run-bp"

    await bridge.publish(run_id, "first", {})
    await bridge.publish(run_id, "second", {})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(received) == 2
    assert received[0].event == "second"
    assert received[1] is END_SENTINEL


@pytest.mark.anyio
async def test_multiple_runs(bridge: MemoryStreamBridge):
    '未说明'
    await bridge.publish("run-a", "event-a", {"a": 1})
    await bridge.publish("run-b", "event-b", {"b": 2})
    await bridge.publish_end("run-a")
    await bridge.publish_end("run-b")

    events_a = []
    async for entry in bridge.subscribe("run-a", heartbeat_interval=1.0):
        events_a.append(entry)
        if entry is END_SENTINEL:
            break

    events_b = []
    async for entry in bridge.subscribe("run-b", heartbeat_interval=1.0):
        events_b.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(events_a) == 2
    assert events_a[0].event == "event-a"
    assert events_a[0].data == {"a": 1}

    assert len(events_b) == 2
    assert events_b[0].event == "event-b"
    assert events_b[0].data == {"b": 2}


@pytest.mark.anyio
async def test_event_id_format(bridge: MemoryStreamBridge):
    '未说明'
    run_id = "run-id-format"
    await bridge.publish(run_id, "test", {"key": "value"})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    event = received[0]
    assert re.match(r"^\d+-\d+$", event.id), f"Expected timestamp-seq format, got {event.id}"


@pytest.mark.anyio
async def test_subscribe_replays_after_last_event_id(bridge: MemoryStreamBridge):
    '未说明'
    run_id = "run-replay"
    await bridge.publish(run_id, "metadata", {"run_id": run_id})
    await bridge.publish(run_id, "values", {"step": 1})
    await bridge.publish(run_id, "updates", {"step": 2})
    await bridge.publish_end(run_id)

    first_pass = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        first_pass.append(entry)
        if entry is END_SENTINEL:
            break

    received = []
    async for entry in bridge.subscribe(
        run_id,
        last_event_id=first_pass[0].id,
        heartbeat_interval=1.0,
    ):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["values", "updates"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_slow_subscriber_does_not_skip_after_buffer_trim():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-slow-subscriber"
    await bridge.publish(run_id, "e1", {"step": 1})
    await bridge.publish(run_id, "e2", {"step": 2})

    stream = bridge._streams[run_id]
    e1_id = stream.events[0].id
    assert stream.start_offset == 0

    await bridge.publish(run_id, "e3", {"step": 3})  # trims e1
    assert stream.start_offset == 1
    assert [entry.event for entry in stream.events] == ["e2", "e3"]

    resumed_after_e1 = []
    async for entry in bridge.subscribe(
        run_id,
        last_event_id=e1_id,
        heartbeat_interval=1.0,
    ):
        resumed_after_e1.append(entry)
        if len(resumed_after_e1) == 2:
            break

    assert [entry.event for entry in resumed_after_e1] == ["e2", "e3"]
    e2_id = resumed_after_e1[0].id

    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(
        run_id,
        last_event_id=e2_id,
        heartbeat_interval=1.0,
    ):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["e3"]
    assert received[-1] is END_SENTINEL


# ---------------------------------------------------------------------------
# Stream termination tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_publish_end_terminates_even_when_history_is_full():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-end-history-full"

    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish(run_id, "event-2", {"n": 2})
    stream = bridge._streams[run_id]
    assert [entry.event for entry in stream.events] == ["event-1", "event-2"]

    await bridge.publish_end(run_id)
    assert [entry.event for entry in stream.events] == ["event-1", "event-2"]

    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in events[:-1]] == ["event-1", "event-2"]
    assert events[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_publish_end_without_history_yields_end_immediately():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-end-empty"
    await bridge.publish_end(run_id)

    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(events) == 1
    assert events[0] is END_SENTINEL


@pytest.mark.anyio
async def test_publish_end_preserves_history_when_space_available():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=10)
    run_id = "run-no-evict"

    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish(run_id, "event-2", {"n": 2})
    await bridge.publish_end(run_id)

    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    # All events plus END should be present
    assert len(events) == 3
    assert events[0].event == "event-1"
    assert events[1].event == "event-2"
    assert events[2] is END_SENTINEL


@pytest.mark.anyio
async def test_concurrent_tasks_end_sentinel():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=4)
    num_runs = 4

    async def producer(run_id: str):
        '未说明'
        for i in range(10):  # More events than queue capacity
            await bridge.publish(run_id, f"event-{i}", {"i": i})
        await bridge.publish_end(run_id)

    async def consumer(run_id: str) -> list:
        '未说明'
        events = []
        async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
            events.append(entry)
            if entry is END_SENTINEL:
                return events
        return events  # pragma: no cover

    run_ids = [f"concurrent-{i}" for i in range(num_runs)]
    results: dict[str, list] = {}

    async def consume_into(run_id: str) -> None:
        '未说明'
        results[run_id] = await consumer(run_id)

    with anyio.fail_after(10):
        async with anyio.create_task_group() as task_group:
            for run_id in run_ids:
                task_group.start_soon(consume_into, run_id)
            await anyio.sleep(0)
            for run_id in run_ids:
                task_group.start_soon(producer, run_id)

    for run_id in run_ids:
        events = results[run_id]
        assert events[-1] is END_SENTINEL, f"Run {run_id} did not receive END sentinel"


# ---------------------------------------------------------------------------
# Unit tests for RedisStreamBridge
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_bridge() -> RedisStreamBridge:
    '未说明'
    return RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=_FakeRedis())


@pytest.mark.anyio
async def test_redis_publish_subscribe(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-1"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish(run_id, "values", {"messages": []})
    await redis_bridge.publish_end(run_id)

    received = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["metadata", "values"]
    assert received[0].data == {"run_id": run_id}
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_replays_after_last_event_id(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-replay"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish(run_id, "values", {"step": 1})
    await redis_bridge.publish_end(run_id)

    first_pass = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        first_pass.append(entry)
        if entry is END_SENTINEL:
            break

    received = []
    async for entry in redis_bridge.subscribe(run_id, last_event_id=first_pass[0].id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_invalid_last_event_id_tails_live_events(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-invalid-last-event-id"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    received = []

    async def publish_later() -> None:
        '未说明'
        await anyio.sleep(0.05)
        await redis_bridge.publish(run_id, "values", {"step": 1})
        await redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in redis_bridge.subscribe(run_id, last_event_id="-1", heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [entry.event for entry in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_invalid_last_event_id_tails_empty_stream(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-invalid-empty"
    received = []

    async def publish_later() -> None:
        '未说明'
        await anyio.sleep(0.05)
        await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
        await redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in redis_bridge.subscribe(run_id, last_event_id="-1", heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [entry.event for entry in received[:-1]] == ["metadata"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_invalid_last_event_id_on_terminal_run_replays_end(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-invalid-terminal"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish_end(run_id)

    received = []
    async for entry in redis_bridge.subscribe(run_id, last_event_id="-1", heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["metadata"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_heartbeat(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-heartbeat"
    await redis_bridge.publish(run_id, "init", {})

    received = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=0.01):
        received.append(entry)
        if entry is HEARTBEAT_SENTINEL:
            break

    assert len(received) == 2
    assert received[0].event == "init"
    assert received[1] is HEARTBEAT_SENTINEL


@pytest.mark.anyio
async def test_redis_publish_end_preserves_data_history_capacity(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-end-capacity"

    await redis_bridge.publish(run_id, "event-1", {"n": 1})
    await redis_bridge.publish(run_id, "event-2", {"n": 2})
    await redis_bridge.publish_end(run_id)

    received = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["event-1", "event-2"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_cleanup_deletes_stream(redis_bridge: RedisStreamBridge):
    '未说明'
    fake = redis_bridge._redis
    run_id = "redis-run-cleanup"

    await redis_bridge.publish(run_id, "event", {})
    await redis_bridge.cleanup(run_id)

    assert fake.deleted == ["deerflow:stream_bridge:redis-run-cleanup"]


@pytest.mark.anyio
async def test_redis_publish_refreshes_stream_ttl():
    '未说明'
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        queue_maxsize=2,
        stream_ttl_seconds=42,
        client=fake,
    )
    run_id = "redis-run-ttl"
    key = "deerflow:stream_bridge:redis-run-ttl"

    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish(run_id, "event-2", {"n": 2})
    await bridge.publish_end(run_id)

    assert fake.expirations == [(key, 42), (key, 42), (key, 42)]


@pytest.mark.anyio
async def test_redis_stream_ttl_can_be_disabled():
    '未说明'
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        queue_maxsize=2,
        stream_ttl_seconds=0,
        client=fake,
    )

    await bridge.publish("redis-run-no-ttl", "event", {})
    await bridge.publish_end("redis-run-no-ttl")

    assert fake.expirations == []


@pytest.mark.anyio
async def test_redis_subscribe_waits_for_first_publish(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-first-publish"
    received = []

    async def publish_later() -> None:
        '未说明'
        await anyio.sleep(0.05)
        await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
        await redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [entry.event for entry in received[:-1]] == ["metadata"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_stream_exists_reports_cleanup(redis_bridge: RedisStreamBridge):
    '未说明'
    run_id = "redis-run-post-cleanup"
    await redis_bridge.publish(run_id, "event-1", {"n": 1})
    await redis_bridge.publish_end(run_id)

    assert await redis_bridge.stream_exists(run_id) is True
    await redis_bridge.cleanup(run_id)
    assert await redis_bridge.stream_exists(run_id) is False


@pytest.mark.anyio
async def test_redis_transient_error_retries():
    '未说明'
    from redis.exceptions import RedisError

    fake = _FakeRedis()
    call_count = 0
    original_xread = fake.xread

    async def flaky_xread(streams, count=None, block=None):
        '未说明'
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RedisError("Transient connection error")
        return await original_xread(streams, count=count, block=block)

    fake.xread = flaky_xread
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=fake)

    run_id = "redis-run-retry"
    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish_end(run_id)

    received = []
    with anyio.fail_after(5):
        async for entry in bridge.subscribe(run_id, heartbeat_interval=0.01):
            received.append(entry)
            if entry is END_SENTINEL:
                break

    assert call_count > 2
    assert [e.event for e in received[:-1]] == ["event-1"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_transient_error_gives_up_after_max_retries():
    '未说明'
    from redis.exceptions import RedisError

    fake = _FakeRedis()

    async def always_fail_xread(streams, count=None, block=None):
        '未说明'
        raise RedisError("Persistent connection error")

    fake.xread = always_fail_xread
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=fake)

    with pytest.raises(RedisError, match="Persistent connection error"):
        async for _ in bridge.subscribe("redis-run-fail", heartbeat_interval=0.01):
            pass


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_make_stream_bridge_defaults():
    '未说明'
    async with make_stream_bridge() as bridge:
        assert isinstance(bridge, MemoryStreamBridge)


# ---------------------------------------------------------------------------
# _resolve_start_offset: O(1) seq-indexed resolution (parity with linear scan)
# ---------------------------------------------------------------------------


def _linear_resolve(stream, last_event_id):
    '未说明'
    if last_event_id is None:
        return stream.start_offset
    for index, entry in enumerate(stream.events):
        if entry.id == last_event_id:
            return stream.start_offset + index + 1
    return stream.start_offset


@pytest.mark.parametrize(
    "event_id,expected",
    [
        ("1718000000000-0", 0),
        ("1718000000000-42", 42),
        ("garbage", None),  # no separator
        ("1718000000000-x", None),  # non-integer seq
        ("", None),
    ],
)
def test_parse_event_seq(event_id, expected):
    '未说明'
    assert MemoryStreamBridge._parse_event_seq(event_id) == expected


@pytest.mark.anyio
async def test_resolve_start_offset_matches_linear_scan():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=4)
    run_id = "run-parity"
    ids = []
    for i in range(10):
        await bridge.publish(run_id, f"e{i}", {"i": i})
        ids.append(bridge._streams[run_id].events[-1].id)  # includes ids that later evict
    stream = bridge._streams[run_id]
    assert stream.start_offset == 6  # 10 published, buffer of 4 retains seq 6..9

    # A foreign id: a retained event's seq but a different timestamp -> must NOT match.
    ts, _, seq_text = stream.events[0].id.rpartition("-")
    foreign_id = f"{int(ts) + 1}-{seq_text}"

    candidates = [None, "garbage", "1718000000000-x", "999999-999999", foreign_id, *ids]
    for eid in candidates:
        assert bridge._resolve_start_offset(stream, eid) == _linear_resolve(stream, eid), eid


@pytest.mark.anyio
async def test_subscribe_with_unknown_last_event_id_replays_from_earliest():
    '未说明'
    bridge = MemoryStreamBridge(queue_maxsize=10)
    run_id = "run-unknown-id"
    await bridge.publish(run_id, "first", {})
    await bridge.publish(run_id, "second", {})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, last_event_id="not-a-real-id", heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["first", "second"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_make_stream_bridge_uses_docker_redis_env(monkeypatch):
    '未说明'
    set_stream_bridge_config(None)
    monkeypatch.setenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "redis://redis:6379/0")
    try:
        async with make_stream_bridge() as bridge:
            assert isinstance(bridge, RedisStreamBridge)
            assert bridge._redis_url == "redis://redis:6379/0"
    finally:
        set_stream_bridge_config(None)


@pytest.mark.anyio
async def test_make_stream_bridge_passes_redis_options(monkeypatch):
    '未说明'
    import deerflow.runtime.stream_bridge.redis as redis_module

    captured: dict = {}

    def fake_from_url(url, **kwargs):
        '未说明'
        captured["url"] = url
        captured.update(kwargs)
        return _FakeRedis()

    monkeypatch.setattr(redis_module.Redis, "from_url", staticmethod(fake_from_url))
    set_stream_bridge_config(
        StreamBridgeConfig(
            type="redis",
            redis_url="redis://fake:6379/0",
            max_connections=50,
            stream_ttl_seconds=42,
        )
    )
    try:
        async with make_stream_bridge() as bridge:
            assert isinstance(bridge, RedisStreamBridge)
            assert bridge._stream_ttl_seconds == 42
        assert captured["max_connections"] == 50
        assert captured["decode_responses"] is True
    finally:
        set_stream_bridge_config(None)


# ---------------------------------------------------------------------------
# Integration tests against a real Redis server
# ---------------------------------------------------------------------------
#
# Opt-in and self-skipping: when no Redis is reachable these are skipped so
# `make test` stays green without Redis. Point at a server with
# DEER_FLOW_TEST_REDIS_URL (defaults to redis://localhost:6379/15 — DB 15 to
# avoid clobbering real data) and select with `pytest -m integration`. They
# cover what _FakeRedis only approximates: real XADD/XREAD semantics, live-tail
# reconnects for malformed Last-Event-ID values, the server <ms>-<seq> ID
# format, and MAXLEN trimming.

REDIS_TEST_URL = os.environ.get("DEER_FLOW_TEST_REDIS_URL", "redis://localhost:6379/15")


def _redis_available() -> bool:
    '未说明'
    try:
        import redis  # sync client, used only for the connectivity probe
    except ImportError:
        return False
    try:
        client = redis.Redis.from_url(REDIS_TEST_URL, socket_connect_timeout=0.5)
        try:
            client.ping()
        finally:
            client.close()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(not _redis_available(), reason=f"Redis not reachable at {REDIS_TEST_URL}")


@pytest.fixture
async def real_redis_bridge():
    '未说明'
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    key_prefix = f"deerflow:test:{uuid.uuid4().hex}"
    bridge = RedisStreamBridge(redis_url=REDIS_TEST_URL, queue_maxsize=2, key_prefix=key_prefix, client=client)
    try:
        yield bridge
    finally:
        async for key in client.scan_iter(f"{key_prefix}:*"):
            await client.delete(key)
        await client.aclose()


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_publish_subscribe_and_id_format(real_redis_bridge):
    '未说明'
    run_id = "integ-basic"
    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await real_redis_bridge.publish(run_id, "values", {"step": 1})
    await real_redis_bridge.publish_end(run_id)

    received = []
    async for entry in real_redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [e.event for e in received[:-1]] == ["metadata", "values"]
    assert received[0].data == {"run_id": run_id}
    assert received[-1] is END_SENTINEL
    # Real Redis stream IDs use the <ms>-<seq> format the fake only approximates.
    assert re.match(r"^\d+-\d+$", received[0].id), received[0].id


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_replays_after_last_event_id(real_redis_bridge):
    '未说明'
    run_id = "integ-replay"
    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await real_redis_bridge.publish(run_id, "values", {"step": 1})
    await real_redis_bridge.publish_end(run_id)

    first_pass = []
    async for entry in real_redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        first_pass.append(entry)
        if entry is END_SENTINEL:
            break

    received = []
    async for entry in real_redis_bridge.subscribe(run_id, last_event_id=first_pass[0].id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [e.event for e in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_invalid_last_event_id_tails_live_events(real_redis_bridge):
    '未说明'
    run_id = "integ-bad-leid"
    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    received = []

    async def publish_later() -> None:
        '未说明'
        await anyio.sleep(0.05)
        await real_redis_bridge.publish(run_id, "values", {"step": 1})
        await real_redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in real_redis_bridge.subscribe(run_id, last_event_id="not-a-valid-id", heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [e.event for e in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_maxlen_trims_history(real_redis_bridge):
    '未说明'
    run_id = "integ-maxlen"
    # Fixture sets queue_maxsize=2; publish more data events than that.
    for i in range(6):
        await real_redis_bridge.publish(run_id, f"event-{i}", {"i": i})

    key = real_redis_bridge._stream_key(run_id)
    length = await real_redis_bridge._redis.xlen(key)
    assert length == 2


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_stream_ttl_reclaims_key():
    '未说明'
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    key_prefix = f"deerflow:test:{uuid.uuid4().hex}"
    bridge = RedisStreamBridge(
        redis_url=REDIS_TEST_URL,
        queue_maxsize=2,
        key_prefix=key_prefix,
        stream_ttl_seconds=1,
        client=client,
    )
    run_id = "integ-ttl"
    key = bridge._stream_key(run_id)
    try:
        await bridge.publish(run_id, "metadata", {"run_id": run_id})
        assert await client.exists(key) == 1
        assert await client.ttl(key) >= 0
        await anyio.sleep(2.0)

        assert await client.exists(key) == 0
    finally:
        async for existing_key in client.scan_iter(f"{key_prefix}:*"):
            await client.delete(existing_key)
        await client.aclose()
