"""本模块覆盖运行 事件 存储的行为、边界与回归场景，确保既有契约稳定。"""

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.fixture
def store():
    """为存储准备隔离的测试依赖，并由夹具作用域管理其生命周期。"""
    return MemoryRunEventStore()


# -- Basic write and query --


class TestPutAndSeq:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_put_returns_dict_with_seq(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello")
        assert "seq" in record
        assert record["seq"] == 1
        assert record["thread_id"] == "t1"
        assert record["run_id"] == "r1"
        assert record["event_type"] == "human_message"
        assert record["category"] == "message"
        assert record["content"] == "hello"
        assert "created_at" in record

    @pytest.mark.anyio
    async def test_seq_strictly_increasing_same_thread(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        r2 = await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        r3 = await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        assert r1["seq"] == 1
        assert r2["seq"] == 2
        assert r3["seq"] == 3

    @pytest.mark.anyio
    async def test_seq_independent_across_threads(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        r2 = await store.put(thread_id="t2", run_id="r2", event_type="human_message", category="message")
        assert r1["seq"] == 1
        assert r2["seq"] == 1

    @pytest.mark.anyio
    async def test_put_respects_provided_created_at(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        ts = "2024-06-01T12:00:00+00:00"
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", created_at=ts)
        assert record["created_at"] == ts

    @pytest.mark.anyio
    async def test_put_metadata_preserved(self, store):
        """验证元数据在预期条件及边界场景下的可观察行为，防止相关回归。"""
        meta = {"model": "gpt-4", "tokens": 100}
        record = await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace", metadata=meta)
        assert record["metadata"] == meta


# -- list_messages --


class TestListMessages:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_only_returns_message_category(self, store):
        """验证消息在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="run_start", category="lifecycle")
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["category"] == "message"

    @pytest.mark.anyio
    async def test_ascending_seq_order(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="first")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="second")
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="third")
        messages = await store.list_messages("t1")
        seqs = [m["seq"] for m in messages]
        assert seqs == sorted(seqs)

    @pytest.mark.anyio
    async def test_before_seq_pagination(self, store):
        """验证分页在预期条件及边界场景下的可观察行为，防止相关回归。"""
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages("t1", before_seq=6, limit=3)
        assert len(messages) == 3
        assert [m["seq"] for m in messages] == [3, 4, 5]

    @pytest.mark.anyio
    async def test_after_seq_pagination(self, store):
        """验证分页在预期条件及边界场景下的可观察行为，防止相关回归。"""
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages("t1", after_seq=7, limit=3)
        assert len(messages) == 3
        assert [m["seq"] for m in messages] == [8, 9, 10]

    @pytest.mark.anyio
    async def test_limit_restricts_count(self, store):
        """验证限制在预期条件及边界场景下的可观察行为，防止相关回归。"""
        for _ in range(20):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=5)
        assert len(messages) == 5

    @pytest.mark.anyio
    async def test_cross_run_unified_ordering(self, store):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="ai_message", category="message")
        messages = await store.list_messages("t1")
        assert [m["seq"] for m in messages] == [1, 2, 3, 4]
        assert messages[0]["run_id"] == "r1"
        assert messages[2]["run_id"] == "r2"

    @pytest.mark.anyio
    async def test_default_returns_latest(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        for _ in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=3)
        assert [m["seq"] for m in messages] == [8, 9, 10]

    @pytest.mark.anyio
    async def test_pagination_with_interleaved_trace_events(self, store):
        # Messages and non-message events interleave, so message seqs are
        # non-contiguous (1, 3, 5, 7, 9). Seq-window pagination must still be
        # correct over the messages-only projection, including when the cursor
        # lands in a gap or exactly on a message seq (exclusive bound).
        """验证分页 追踪在预期条件及边界场景下的可观察行为，防止相关回归。"""
        for i in range(10):
            category = "message" if i % 2 == 0 else "trace"
            await store.put(thread_id="t1", run_id="r1", event_type="e", category=category, content=str(i))

        assert [m["seq"] for m in await store.list_messages("t1")] == [1, 3, 5, 7, 9]
        # before_seq in a gap: seq < 6 -> [1, 3, 5], last 2
        assert [m["seq"] for m in await store.list_messages("t1", before_seq=6, limit=2)] == [3, 5]
        # before_seq on a message seq is exclusive: seq < 5 -> [1, 3]
        assert [m["seq"] for m in await store.list_messages("t1", before_seq=5, limit=5)] == [1, 3]
        # after_seq in a gap: seq > 4 -> [5, 7, 9], first 2
        assert [m["seq"] for m in await store.list_messages("t1", after_seq=4, limit=2)] == [5, 7]
        # after_seq on a message seq is exclusive: seq > 5 -> [7, 9]
        assert [m["seq"] for m in await store.list_messages("t1", after_seq=5, limit=5)] == [7, 9]


# -- list_events --


class TestListEvents:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_returns_all_categories_for_run(self, store):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="run_start", category="lifecycle")
        events = await store.list_events("t1", "r1")
        assert len(events) == 3

    @pytest.mark.anyio
    async def test_event_types_filter(self, store):
        """验证事件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="llm_start", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="tool_start", category="trace")
        events = await store.list_events("t1", "r1", event_types=["llm_end"])
        assert len(events) == 1
        assert events[0]["event_type"] == "llm_end"

    @pytest.mark.anyio
    async def test_only_returns_specified_run(self, store):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        events = await store.list_events("t1", "r1")
        assert len(events) == 1
        assert events[0]["run_id"] == "r1"


# -- list_messages_by_run --


class TestListMessagesByRun:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_only_messages_for_specified_run(self, store):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        messages = await store.list_messages_by_run("t1", "r1")
        assert len(messages) == 1
        assert messages[0]["run_id"] == "r1"
        assert messages[0]["category"] == "message"


# -- count_messages --


class TestCountMessages:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_counts_only_message_category(self, store):
        """验证消息在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        assert await store.count_messages("t1") == 2


# -- put_batch --


class TestPutBatch:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_batch_assigns_seq(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message", "content": "a"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message", "content": "b"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "llm_end", "category": "trace"},
        ]
        results = await store.put_batch(events)
        assert len(results) == 3
        assert all("seq" in r for r in results)

    @pytest.mark.anyio
    async def test_batch_seq_strictly_increasing(self, store):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message"},
        ]
        results = await store.put_batch(events)
        assert results[0]["seq"] == 1
        assert results[1]["seq"] == 2


# -- delete --


class TestDelete:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_delete_by_thread(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        count = await store.delete_by_thread("t1")
        assert count == 3
        assert await store.list_messages("t1") == []
        assert await store.count_messages("t1") == 0

    @pytest.mark.anyio
    async def test_delete_by_run(self, store):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        count = await store.delete_by_run("t1", "r2")
        assert count == 2
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["run_id"] == "r1"

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_returns_zero(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert await store.delete_by_thread("nope") == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent_run_returns_zero(self, store):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        assert await store.delete_by_run("t1", "nope") == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_for_run_returns_zero(self, store):
        """验证会话 运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert await store.delete_by_run("nope", "r1") == 0


# -- Edge cases --


class TestEdgeCases:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_empty_thread_list_messages(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert await store.list_messages("empty") == []

    @pytest.mark.anyio
    async def test_empty_run_list_events(self, store):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert await store.list_events("empty", "r1") == []

    @pytest.mark.anyio
    async def test_empty_thread_count_messages(self, store):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert await store.count_messages("empty") == 0


# -- DB-specific tests --


class TestDbRunEventStore:
    """集中覆盖当前测试分支与回归边界。"""

    @pytest.mark.anyio
    async def test_postgres_max_seq_uses_advisory_lock_without_for_update(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from sqlalchemy.dialects import postgresql

        from deerflow.runtime.events.store.db import DbRunEventStore

        class FakeSession:
            """集中覆盖当前测试分支与回归边界。"""
            def __init__(self):
                """准备可控测试资源与状态，供后续断言读取。"""
                self.dialect = postgresql.dialect()
                self.execute_calls = []
                self.scalar_stmt = None

            def get_bind(self):
                """处理获取相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
                return self

            async def execute(self, stmt, params=None):
                """准备可控测试资源与状态，供后续断言读取。"""
                self.execute_calls.append((stmt, params))

            async def scalar(self, stmt):
                """准备可控测试资源与状态，供后续断言读取。"""
                self.scalar_stmt = stmt
                return 41

        session = FakeSession()

        max_seq = await DbRunEventStore._max_seq_for_thread(session, "thread-1")

        assert max_seq == 41
        assert session.execute_calls
        assert session.execute_calls[0][1] == {"thread_id": "thread-1"}
        assert "pg_advisory_xact_lock" in str(session.execute_calls[0][0])
        compiled = str(session.scalar_stmt.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" not in compiled

    @pytest.mark.anyio
    async def test_basic_crud(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        r = await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert r["seq"] == 1
        r2 = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="hello")
        assert r2["seq"] == 2

        messages = await s.list_messages("t1")
        assert len(messages) == 2

        count = await s.count_messages("t1")
        assert count == 2

        await close_engine()

    @pytest.mark.anyio
    async def test_trace_content_truncation(self, tmp_path):
        """验证追踪在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory(), max_trace_content=100)

        long = "x" * 200
        r = await s.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace", content=long)
        assert len(r["content"]) == 100
        assert r["metadata"].get("content_truncated") is True

        # message content NOT truncated
        m = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content=long)
        assert len(m["content"]) == 200

        await close_engine()

    @pytest.mark.anyio
    async def test_structured_content_round_trips(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        content = [{"type": "text", "text": "hello"}, {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}}]
        record = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content=content)

        assert record["content"] == content
        assert record["metadata"]["content_is_json"] is True
        assert "content_is_dict" not in record["metadata"]

        messages = await s.list_messages("t1")
        assert messages[0]["content"] == content
        assert messages[0]["metadata"]["content_is_json"] is True

        await close_engine()

    @pytest.mark.anyio
    async def test_pagination(self, tmp_path):
        """验证分页在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        for i in range(10):
            await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))

        # before_seq
        msgs = await s.list_messages("t1", before_seq=6, limit=3)
        assert [m["seq"] for m in msgs] == [3, 4, 5]

        # after_seq
        msgs = await s.list_messages("t1", after_seq=7, limit=3)
        assert [m["seq"] for m in msgs] == [8, 9, 10]

        # default (latest)
        msgs = await s.list_messages("t1", limit=3)
        assert [m["seq"] for m in msgs] == [8, 9, 10]

        await close_engine()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="ai_message", category="message")
        c = await s.delete_by_run("t1", "r2")
        assert c == 1
        assert await s.count_messages("t1") == 1

        c = await s.delete_by_thread("t1")
        assert c == 1
        assert await s.count_messages("t1") == 0

        await close_engine()

    @pytest.mark.anyio
    async def test_put_batch_seq_continuity(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        events = [{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"} for _ in range(50)]
        results = await s.put_batch(events)
        seqs = [r["seq"] for r in results]
        assert seqs == list(range(1, 51))
        await close_engine()

    @pytest.mark.anyio
    async def test_put_batch_accepts_structured_content(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        content = [{"messages": [{"type": "ai", "content": ""}]}]
        results = await s.put_batch(
            [
                {
                    "thread_id": "t1",
                    "run_id": "r1",
                    "event_type": "run.end",
                    "category": "outputs",
                    "content": content,
                }
            ]
        )

        assert results[0]["content"] == content
        assert results[0]["metadata"]["content_is_json"] is True

        events = await s.list_events("t1", "r1")
        assert events[0]["content"] == content
        assert events[0]["metadata"]["content_is_json"] is True

        await close_engine()

    @pytest.mark.anyio
    async def test_dict_content_keeps_legacy_metadata_flag(self, tmp_path):
        """验证元数据在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        content = {"status": "success"}
        record = await s.put(thread_id="t1", run_id="r1", event_type="run.end", category="outputs", content=content)

        assert record["content"] == content
        assert record["metadata"]["content_is_json"] is True
        assert record["metadata"]["content_is_dict"] is True

        await close_engine()


class TestDbRunEventStoreWriteLock:
    """集中覆盖当前测试分支与回归边界。"""

    def test_get_write_lock_same_thread_returns_same_lock(self):
        """验证获取 写入 会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        import asyncio
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store.db import DbRunEventStore

        # The lock accessor does not touch the session factory, so a stub is fine.
        store = DbRunEventStore(MagicMock())

        lock = store._get_write_lock("thread-1")
        assert isinstance(lock, asyncio.Lock)
        assert store._get_write_lock("thread-1") is lock

    def test_get_write_lock_distinct_threads_get_distinct_locks(self):
        """验证获取 写入 获取在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store.db import DbRunEventStore

        store = DbRunEventStore(MagicMock())

        assert store._get_write_lock("thread-1") is not store._get_write_lock("thread-2")

    @pytest.mark.anyio
    async def test_concurrent_put_batch_same_thread_has_no_seq_collision(self, tmp_path):
        """验证并发 会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        import asyncio

        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        def _batch(run_id: str):
            """准备可控测试资源与状态，供后续断言读取。"""
            return [{"thread_id": "t1", "run_id": run_id, "event_type": "trace", "category": "trace"} for _ in range(20)]

        # Fire two concurrent batches at the same thread; without the per-thread
        # lock this races on seq and raises IntegrityError / duplicates seq.
        results = await asyncio.gather(s.put_batch(_batch("r1")), s.put_batch(_batch("r2")))

        all_seqs = [r["seq"] for batch in results for r in batch]
        assert len(all_seqs) == 40
        # Seq values are unique and contiguous 1..40 across both writers.
        assert sorted(all_seqs) == list(range(1, 41))

        await close_engine()

    @pytest.mark.anyio
    async def test_delete_by_thread_evicts_orphaned_write_lock(self, tmp_path):
        """验证会话 写入在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        # A write materializes the per-thread lock in the registry.
        await s.put_batch([{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"}])
        assert "t1" in s._write_locks

        # Deleting the thread must evict the now-orphaned lock so the registry
        # does not grow unbounded across the singleton store's lifetime.
        await s.delete_by_thread("t1")
        assert "t1" not in s._write_locks

        # A subsequent write recreates a fresh lock and seq restarts from 1.
        result = await s.put_batch([{"thread_id": "t1", "run_id": "r2", "event_type": "trace", "category": "trace"}])
        assert "t1" in s._write_locks
        assert result[0]["seq"] == 1

        await close_engine()

    @pytest.mark.anyio
    async def test_delete_by_thread_keeps_lock_held_by_inflight_writer(self, tmp_path):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        # Simulate a writer mid-flight by holding the lock; the eviction must
        # not drop a lock another coroutine is actively using.
        lock = s._get_write_lock("t1")
        await lock.acquire()
        try:
            await s.delete_by_thread("t1")
            assert "t1" in s._write_locks
            assert s._write_locks["t1"] is lock
        finally:
            lock.release()

        await close_engine()


# -- Factory tests --


class TestMakeRunEventStore:
    """集中覆盖当前测试分支与回归边界。"""

    @pytest.mark.anyio
    async def test_memory_backend_default(self):
        """验证内存在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.runtime.events.store import make_run_event_store

        store = make_run_event_store(None)
        assert type(store).__name__ == "MemoryRunEventStore"

    @pytest.mark.anyio
    async def test_memory_backend_explicit(self):
        """验证内存在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "memory"
        store = make_run_event_store(config)
        assert type(store).__name__ == "MemoryRunEventStore"

    @pytest.mark.anyio
    async def test_db_backend_with_engine(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from unittest.mock import MagicMock

        from deerflow.persistence.engine import close_engine, init_engine
        from deerflow.runtime.events.store import make_run_event_store

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))

        config = MagicMock()
        config.backend = "db"
        config.max_trace_content = 10240
        store = make_run_event_store(config)
        assert type(store).__name__ == "DbRunEventStore"
        await close_engine()

    @pytest.mark.anyio
    async def test_db_backend_no_engine_falls_back(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from unittest.mock import MagicMock

        from deerflow.persistence.engine import close_engine, init_engine
        from deerflow.runtime.events.store import make_run_event_store

        await init_engine("memory")  # no engine created

        config = MagicMock()
        config.backend = "db"
        store = make_run_event_store(config)
        assert type(store).__name__ == "MemoryRunEventStore"
        await close_engine()

    @pytest.mark.anyio
    async def test_jsonl_backend(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "jsonl"
        store = make_run_event_store(config)
        assert type(store).__name__ == "JsonlRunEventStore"

    @pytest.mark.anyio
    async def test_unknown_backend_raises(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "redis"
        with pytest.raises(ValueError, match="Unknown"):
            make_run_event_store(config)


# -- JSONL-specific tests --


class TestJsonlRunEventStore:
    """集中覆盖当前测试分支与回归边界。"""
    @pytest.mark.anyio
    async def test_basic_crud(self, tmp_path):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        r = await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert r["seq"] == 1
        messages = await s.list_messages("t1")
        assert len(messages) == 1

    @pytest.mark.anyio
    async def test_file_at_correct_path(self, tmp_path):
        """验证文件 路径在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        assert (tmp_path / "jsonl" / "threads" / "t1" / "runs" / "r1.jsonl").exists()

    @pytest.mark.anyio
    async def test_cross_run_messages(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        messages = await s.list_messages("t1")
        assert len(messages) == 2
        assert [m["seq"] for m in messages] == [1, 2]

    @pytest.mark.anyio
    async def test_delete_by_run(self, tmp_path):
        """验证运行在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        c = await s.delete_by_run("t1", "r2")
        assert c == 1
        assert not (tmp_path / "jsonl" / "threads" / "t1" / "runs" / "r2.jsonl").exists()
        assert await s.count_messages("t1") == 1
