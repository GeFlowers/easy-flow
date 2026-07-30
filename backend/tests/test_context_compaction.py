"""\u672c\u6a21\u5757\u8986\u76d6\u76f8\u5173\u6d4b\u8bd5\uff0c\u56fa\u5b9a\u516c\u5f00\u884c\u4e3a\u3001\u5931\u8d25\u5904\u7406\u4e0e\u72b6\u6001\u8fb9\u754c\u3002"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.runtime import context_compaction
from deerflow.runtime.context_compaction import compact_thread_context


class _FakeCheckpointer:
    """\u6b64\u6d4b\u8bd5\u7ec4\u5f52\u96c6\u540c\u4e00\u7ec4\u4ef6\u7684\u7528\u4f8b\uff0c\u5206\u522b\u7ea6\u675f\u6b63\u5e38\u6d41\u7a0b\u4e0e\u5173\u952e\u8fb9\u754c\u6761\u4ef6\u3002"""
    def __init__(self, checkpoint: dict, metadata: dict | None = None) -> None:
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        self.checkpoint = checkpoint
        self.metadata = metadata or {"step": 4, "created_at": "2026-07-06T00:00:00+00:00"}
        self.put_args = None

    async def aget_tuple(self, config):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        return SimpleNamespace(
            checkpoint=self.checkpoint,
            metadata=self.metadata,
            config={"configurable": {"thread_id": config["configurable"]["thread_id"], "checkpoint_id": "ckpt-old", "checkpoint_ns": ""}},
        )

    def get_next_version(self, current_version, _channel):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        if current_version is None:
            return 1
        return current_version + 1

    async def aput(self, config, checkpoint, metadata, new_versions):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        self.put_args = (config, checkpoint, metadata, new_versions)
        return {"configurable": {"checkpoint_id": checkpoint["id"]}}


class _FakeCompactionMiddleware:
    """\u6b64\u6d4b\u8bd5\u7ec4\u5f52\u96c6\u540c\u4e00\u7ec4\u4ef6\u7684\u7528\u4f8b\uff0c\u5206\u522b\u7ea6\u675f\u6b63\u5e38\u6d41\u7a0b\u4e0e\u5173\u952e\u8fb9\u754c\u6761\u4ef6\u3002"""
    def __init__(self, *, should_compact: bool = True) -> None:
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        self.should_compact = should_compact
        self.prepare_calls = 0
        self.runtime_contexts: list[dict] = []

    def _prepare_compaction(self, state, *, force=False):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        self.prepare_calls += 1
        if not self.should_compact:
            return None
        return (state["messages"][:-1], state["messages"][-1:], state.get("summary_text"), 123)

    async def acompact_state(self, state, runtime, *, force=False):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        self.runtime_contexts.append(dict(runtime.context))
        prepared = self._prepare_compaction(state, force=force)
        if prepared is None:
            return None
        messages_to_summarize, preserved_messages, _previous_summary, total_tokens = prepared
        return SimpleNamespace(
            summary_text="COMPRESSED SUMMARY",
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            total_tokens=total_tokens,
        )


class _SyncCheckpointer:
    """\u6b64\u6d4b\u8bd5\u7ec4\u5f52\u96c6\u540c\u4e00\u7ec4\u4ef6\u7684\u7528\u4f8b\uff0c\u5206\u522b\u7ea6\u675f\u6b63\u5e38\u6d41\u7a0b\u4e0e\u5173\u952e\u8fb9\u754c\u6761\u4ef6\u3002"""
    def __init__(self, checkpoint: dict, metadata: dict | None = None) -> None:
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        self.checkpoint = checkpoint
        self.metadata = metadata or {"step": 4, "created_at": "2026-07-06T00:00:00+00:00"}
        self.put_args = None

    def get_tuple(self, config):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        return SimpleNamespace(
            checkpoint=self.checkpoint,
            metadata=self.metadata,
            config={"configurable": {"thread_id": config["configurable"]["thread_id"], "checkpoint_id": "ckpt-old", "checkpoint_ns": ""}},
        )

    def get_next_version(self, current_version, _channel):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        if current_version is None:
            return 1
        return current_version + 1

    def put(self, config, checkpoint, metadata, new_versions):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        self.put_args = (config, checkpoint, metadata, new_versions)
        return {"configurable": {"checkpoint_id": checkpoint["id"]}}


class _RejectDeepcopy:
    """\u6b64\u6d4b\u8bd5\u7ec4\u5f52\u96c6\u540c\u4e00\u7ec4\u4ef6\u7684\u7528\u4f8b\uff0c\u5206\u522b\u7ea6\u675f\u6b63\u5e38\u6d41\u7a0b\u4e0e\u5173\u952e\u8fb9\u754c\u6761\u4ef6\u3002"""
    def __deepcopy__(self, _memo):
        """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
        raise AssertionError("compact_thread_context must not deepcopy unrelated channel values")


@pytest.mark.asyncio
async def test_compact_thread_context_writes_summary_and_bumps_changed_channels(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u5f02\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc717\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="latest question"),
    ]
    checkpointer = _FakeCheckpointer(
        {
            "id": "ckpt-old",
            "channel_values": {"messages": messages, "summary_text": "OLD SUMMARY", "sandbox": _RejectDeepcopy()},
            "channel_versions": {"messages": 7, "summary_text": 3, "title": 2},
        }
    )
    middleware = _FakeCompactionMiddleware()
    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: middleware,
    )

    result = await compact_thread_context(
        checkpointer,
        "thread-1",
        app_config=SimpleNamespace(),
        user_id="user-1",
        agent_name="research-agent",
    )

    assert result.compacted is True
    assert result.removed_message_count == 2
    assert result.preserved_message_count == 1
    assert result.summary_updated is True
    assert result.total_tokens == 123

    assert checkpointer.put_args is not None
    _config, written_checkpoint, written_metadata, new_versions = checkpointer.put_args
    assert written_checkpoint["channel_values"]["messages"] == [messages[-1]]
    assert written_checkpoint["channel_values"]["summary_text"] == "COMPRESSED SUMMARY"
    assert isinstance(written_checkpoint["channel_values"]["sandbox"], _RejectDeepcopy)
    assert written_checkpoint["channel_versions"]["messages"] == 8
    assert written_checkpoint["channel_versions"]["summary_text"] == 4
    assert written_checkpoint["channel_versions"]["title"] == 2
    assert new_versions == {"messages": 8, "summary_text": 4}
    assert written_metadata["writes"]["manual_compaction"]["messages"] == {
        "removed": 2,
        "preserved": 1,
    }
    assert "COMPRESSED SUMMARY" not in str(written_metadata["writes"])
    assert middleware.prepare_calls == 1
    assert middleware.runtime_contexts == [
        {"thread_id": "thread-1", "user_id": "user-1", "agent_name": "research-agent"},
    ]


@pytest.mark.asyncio
async def test_compact_thread_context_returns_noop_without_writing(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u5f02\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc74\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    checkpointer = _FakeCheckpointer(
        {
            "id": "ckpt-old",
            "channel_values": {"messages": [HumanMessage(content="latest only")]},
            "channel_versions": {"messages": 1},
        }
    )
    middleware = _FakeCompactionMiddleware(should_compact=False)
    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: middleware,
    )

    result = await compact_thread_context(checkpointer, "thread-1", app_config=SimpleNamespace())

    assert result.compacted is False
    assert result.reason == "not_enough_messages"
    assert checkpointer.put_args is None
    assert middleware.prepare_calls == 1


@pytest.mark.asyncio
async def test_compact_thread_context_supports_sync_checkpointer_methods(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u5f02\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="latest question"),
    ]
    checkpointer = _SyncCheckpointer(
        {
            "id": "ckpt-old",
            "channel_values": {"messages": messages, "summary_text": "OLD SUMMARY"},
            "channel_versions": {"messages": 7, "summary_text": 3},
        }
    )
    monkeypatch.setattr(
        context_compaction,
        "_create_compaction_middleware",
        lambda **_kwargs: _FakeCompactionMiddleware(),
    )

    result = await compact_thread_context(checkpointer, "thread-1", app_config=SimpleNamespace())

    assert result.compacted is True
    assert checkpointer.put_args is not None
