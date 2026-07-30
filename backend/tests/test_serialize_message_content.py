'未说明'

from langchain_core.messages import ToolMessage

from deerflow.client import DeerFlowClient

# ---------------------------------------------------------------------------
# _serialize_message
# ---------------------------------------------------------------------------


class TestSerializeToolMessageContent:
    '未说明'

    def test_string_content(self):
        '未说明'
        msg = ToolMessage(content="ok", tool_call_id="tc1", name="search")
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "ok"
        assert result["type"] == "tool"

    def test_list_of_blocks_content(self):
        '未说明'
        msg = ToolMessage(
            content=[{"type": "text", "text": "hello world"}],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "hello world"
        # Must NOT contain Python repr artifacts
        assert "[" not in result["content"]
        assert "{" not in result["content"]

    def test_multiple_text_blocks(self):
        '未说明'
        msg = ToolMessage(
            content=[
                {"type": "text", "text": "line 1"},
                {"type": "text", "text": "line 2"},
            ],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "line 1\nline 2"

    def test_string_chunks_are_joined_without_newlines(self):
        '未说明'
        msg = ToolMessage(
            content=['{"a"', ': "b"}'],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == '{"a": "b"}'

    def test_mixed_string_chunks_and_blocks(self):
        '未说明'
        msg = ToolMessage(
            content=["prefix", "-continued", {"type": "text", "text": "block text"}],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "prefix-continued\nblock text"

    def test_mixed_blocks_with_non_text(self):
        '未说明'
        msg = ToolMessage(
            content=[
                {"type": "text", "text": "found results"},
                {"type": "image_url", "image_url": {"url": "http://img.png"}},
            ],
            tool_call_id="tc1",
            name="view_image",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "found results"

    def test_empty_list_content(self):
        '未说明'
        msg = ToolMessage(content=[], tool_call_id="tc1", name="search")
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == ""

    def test_plain_string_in_list(self):
        '未说明'
        msg = ToolMessage(
            content=["plain text block"],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "plain text block"

    def test_unknown_content_type_falls_back(self):
        '未说明'
        msg = ToolMessage(content=42, tool_call_id="tc1", name="calc")
        result = DeerFlowClient._serialize_message(msg)
        # int → not str, not list → falls to str()
        assert result["content"] == "42"


# ---------------------------------------------------------------------------
# _extract_text (already existed, but verify it also covers ToolMessage paths)
# ---------------------------------------------------------------------------


class TestExtractText:
    '未说明'

    def test_string_passthrough(self):
        '未说明'
        assert DeerFlowClient._extract_text("hello") == "hello"

    def test_list_text_blocks(self):
        '未说明'
        assert DeerFlowClient._extract_text([{"type": "text", "text": "hi"}]) == "hi"

    def test_empty_list(self):
        '未说明'
        assert DeerFlowClient._extract_text([]) == ""

    def test_fallback_non_iterable(self):
        '未说明'
        assert DeerFlowClient._extract_text(123) == "123"
