'未说明'

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.client import DeerFlowClient

# ---------------------------------------------------------------------------
# _serialize_message — usage_metadata passthrough
# ---------------------------------------------------------------------------


class TestSerializeMessageUsageMetadata:
    '未说明'

    def test_ai_message_with_usage_metadata(self):
        '未说明'
        msg = AIMessage(
            content="Hello",
            id="msg-1",
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "ai"
        assert result["usage_metadata"] == {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }

    def test_ai_message_without_usage_metadata(self):
        '未说明'
        msg = AIMessage(content="Hello", id="msg-2")
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "ai"
        assert "usage_metadata" not in result

    def test_tool_message_never_has_usage_metadata(self):
        '未说明'
        msg = ToolMessage(content="result", tool_call_id="tc-1", name="search")
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "tool"
        assert "usage_metadata" not in result

    def test_human_message_never_has_usage_metadata(self):
        '未说明'
        msg = HumanMessage(content="Hi")
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "human"
        assert "usage_metadata" not in result

    def test_ai_message_with_tool_calls_and_usage(self):
        '未说明'
        msg = AIMessage(
            content="",
            id="msg-3",
            tool_calls=[{"name": "search", "args": {"q": "test"}, "id": "tc-1"}],
            usage_metadata={"input_tokens": 200, "output_tokens": 30, "total_tokens": 230},
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "ai"
        assert result["tool_calls"] == [{"name": "search", "args": {"q": "test"}, "id": "tc-1"}]
        assert result["usage_metadata"]["input_tokens"] == 200

    def test_ai_message_with_zero_usage(self):
        '未说明'
        msg = AIMessage(
            content="Hello",
            id="msg-4",
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["usage_metadata"] == {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }


# ---------------------------------------------------------------------------
# Cumulative usage tracking (simulated, no real agent)
# ---------------------------------------------------------------------------


class TestCumulativeUsageTracking:
    '未说明'

    def test_single_message_usage(self):
        '未说明'
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        usage = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
        cumulative["output_tokens"] += usage.get("output_tokens", 0) or 0
        cumulative["total_tokens"] += usage.get("total_tokens", 0) or 0
        assert cumulative == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_multiple_messages_usage(self):
        '未说明'
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        messages_usage = [
            {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            {"input_tokens": 200, "output_tokens": 30, "total_tokens": 230},
            {"input_tokens": 150, "output_tokens": 80, "total_tokens": 230},
        ]
        for usage in messages_usage:
            cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
            cumulative["output_tokens"] += usage.get("output_tokens", 0) or 0
            cumulative["total_tokens"] += usage.get("total_tokens", 0) or 0
        assert cumulative == {"input_tokens": 450, "output_tokens": 160, "total_tokens": 610}

    def test_missing_usage_keys_treated_as_zero(self):
        '未说明'
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        usage = {"input_tokens": 50}  # missing output_tokens, total_tokens
        cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
        cumulative["output_tokens"] += usage.get("output_tokens", 0) or 0
        cumulative["total_tokens"] += usage.get("total_tokens", 0) or 0
        assert cumulative == {"input_tokens": 50, "output_tokens": 0, "total_tokens": 0}

    def test_empty_usage_metadata_stays_zero(self):
        '未说明'
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        # Simulate: AI message without usage_metadata
        usage = None
        if usage:
            cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
        assert cumulative == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# ---------------------------------------------------------------------------
# stream() integration — usage_metadata in end event and messages-tuple
# ---------------------------------------------------------------------------


def _make_agent_mock(chunks):
    '未说明'
    agent = MagicMock()
    agent.stream.return_value = iter(chunks)
    return agent


def _mock_app_config():
    '未说明'
    model = MagicMock()
    model.name = "test-model"
    model.model = "test-model"
    model.supports_thinking = False
    model.supports_reasoning_effort = False
    model.model_dump.return_value = {"name": "test-model", "use": "langchain_openai:ChatOpenAI"}
    config = MagicMock()
    config.models = [model]
    return config


class TestStreamUsageIntegration:
    '未说明'

    def _make_client(self):
        '未说明'
        with patch("deerflow.client.get_app_config", return_value=_mock_app_config()):
            return DeerFlowClient()

    def test_stream_emits_usage_in_messages_tuple(self):
        '未说明'
        client = self._make_client()
        ai = AIMessage(
            content="Hello!",
            id="ai-1",
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )
        chunks = [
            {"messages": [HumanMessage(content="hi", id="h-1"), ai]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t1"))

        # Find the AI text messages-tuple event
        ai_text_events = [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "ai" and e.data.get("content") == "Hello!"]
        assert len(ai_text_events) == 1
        event_data = ai_text_events[0].data
        assert "usage_metadata" in event_data
        assert event_data["usage_metadata"] == {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }

    def test_stream_cumulative_usage_in_end_event(self):
        '未说明'
        client = self._make_client()
        ai1 = AIMessage(
            content="First",
            id="ai-1",
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )
        ai2 = AIMessage(
            content="Second",
            id="ai-2",
            usage_metadata={"input_tokens": 200, "output_tokens": 30, "total_tokens": 230},
        )
        chunks = [
            {"messages": [HumanMessage(content="hi", id="h-1"), ai1]},
            {"messages": [HumanMessage(content="hi", id="h-1"), ai1, ai2]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t1"))

        # Find the end event
        end_events = [e for e in events if e.type == "end"]
        assert len(end_events) == 1
        end_data = end_events[0].data
        assert "usage" in end_data
        assert end_data["usage"] == {
            "input_tokens": 300,
            "output_tokens": 80,
            "total_tokens": 380,
        }

    def test_stream_no_usage_metadata_no_usage_in_events(self):
        '未说明'
        client = self._make_client()
        ai = AIMessage(content="Hello!", id="ai-1")
        chunks = [
            {"messages": [HumanMessage(content="hi", id="h-1"), ai]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t1"))

        # messages-tuple AI event should NOT have usage_metadata
        ai_text_events = [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "ai" and e.data.get("content") == "Hello!"]
        assert len(ai_text_events) == 1
        assert "usage_metadata" not in ai_text_events[0].data

        # end event should still exist but with zero usage
        end_events = [e for e in events if e.type == "end"]
        assert len(end_events) == 1
        usage = end_events[0].data.get("usage", {})
        assert usage.get("input_tokens", 0) == 0
        assert usage.get("output_tokens", 0) == 0
        assert usage.get("total_tokens", 0) == 0

    def test_stream_usage_with_tool_calls(self):
        '未说明'
        client = self._make_client()
        ai_tool = AIMessage(
            content="",
            id="ai-1",
            tool_calls=[{"name": "search", "args": {"q": "test"}, "id": "tc-1"}],
            usage_metadata={"input_tokens": 150, "output_tokens": 25, "total_tokens": 175},
        )
        tool_result = ToolMessage(content="result", id="tm-1", tool_call_id="tc-1", name="search")
        ai_final = AIMessage(
            content="Here is the answer.",
            id="ai-2",
            usage_metadata={"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
        )
        chunks = [
            {"messages": [HumanMessage(content="search", id="h-1"), ai_tool]},
            {"messages": [HumanMessage(content="search", id="h-1"), ai_tool, tool_result]},
            {"messages": [HumanMessage(content="search", id="h-1"), ai_tool, tool_result, ai_final]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("search", thread_id="t1"))

        # Final AI text event should have usage_metadata
        ai_text_events = [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "ai" and e.data.get("content") == "Here is the answer."]
        assert len(ai_text_events) == 1
        assert ai_text_events[0].data["usage_metadata"]["total_tokens"] == 300

        # end event should have cumulative usage
        end_events = [e for e in events if e.type == "end"]
        assert end_events[0].data["usage"]["input_tokens"] == 350
        assert end_events[0].data["usage"]["output_tokens"] == 125
        assert end_events[0].data["usage"]["total_tokens"] == 475
