"""\u672c\u6a21\u5757\u8986\u76d6\u76f8\u5173\u6d4b\u8bd5\uff0c\u56fa\u5b9a\u516c\u5f00\u884c\u4e3a\u3001\u5931\u8d25\u5904\u7406\u4e0e\u72b6\u6001\u8fb9\u754c\u3002"""

from __future__ import annotations

import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.models.credential_loader import CodexCliCredential


def _make_model(**kwargs):
    """\u51c6\u5907\u9694\u79bb\u7684\u6d4b\u8bd5\u524d\u7f6e\u6761\u4ef6\uff0c\u907f\u514d\u771f\u5b9e\u5916\u90e8\u4f9d\u8d56\u5f71\u54cd\u540e\u7eed\u65ad\u8a00\u3002"""
    from deerflow.models.openai_codex_provider import CodexChatModel

    cred = CodexCliCredential(access_token="tok-test", account_id="acc-test")
    with patch("deerflow.models.openai_codex_provider.load_codex_cli_credential", return_value=cred):
        return CodexChatModel(model="gpt-5.4", reasoning_effort="medium", **kwargs)


# ---------------------------------------------------------------------------
# 序列化协议
# ---------------------------------------------------------------------------


def test_is_lc_serializable_returns_true():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel.is_lc_serializable() is True


def test_to_json_produces_constructor_type():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    result = model.to_json()
    assert result["type"] == "constructor"
    assert "kwargs" in result


def test_to_json_contains_model_and_reasoning_effort():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    result = model.to_json()
    assert result["kwargs"]["model"] == "gpt-5.4"
    assert result["kwargs"]["reasoning_effort"] == "medium"


def test_to_json_does_not_leak_access_token():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc73\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    result = model.to_json()
    kwargs_str = json.dumps(result["kwargs"])
    assert "tok-test" not in kwargs_str
    assert "_access_token" not in kwargs_str
    assert "_account_id" not in kwargs_str


# ---------------------------------------------------------------------------
# \u6b64\u5904\u8bf4\u660e\u8be5\u6d4b\u8bd5\u6bb5\u7684\u524d\u7f6e\u6761\u4ef6\u3001\u8c03\u7528\u9650\u5236\u53ca\u9884\u671f\u8fb9\u754c\u3002
# ---------------------------------------------------------------------------


def test_parse_response_text_content():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello world"}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "model": "gpt-5.4",
    }
    result = model._parse_response(response)
    assert result.generations[0].message.content == "Hello world"


def test_parse_response_populates_usage_metadata():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc76\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello world"}],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
        "model": "gpt-5.4",
    }

    result = model._parse_response(response)

    meta = result.generations[0].message.usage_metadata
    assert meta is not None
    assert meta["input_tokens"] == 10
    assert meta["output_tokens"] == 5
    assert meta["total_tokens"] == 15
    assert meta["input_token_details"]["cache_read"] == 3
    assert meta["output_token_details"]["reasoning"] == 2


def test_parse_response_reasoning_content():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    response = {
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "I reasoned about this."}],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Answer"}],
            },
        ],
        "usage": {},
    }
    result = model._parse_response(response)
    msg = result.generations[0].message
    assert msg.content == "Answer"
    assert msg.additional_kwargs["reasoning_content"] == "I reasoned about this."


def test_parse_response_tool_call():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc74\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "web_search",
                "arguments": '{"query": "test"}',
                "call_id": "call_abc",
            }
        ],
        "usage": {},
    }
    result = model._parse_response(response)
    tool_calls = result.generations[0].message.tool_calls
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "web_search"
    assert tool_calls[0]["args"] == {"query": "test"}
    assert tool_calls[0]["id"] == "call_abc"


def test_parse_response_invalid_tool_call_arguments():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc73\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "bad_tool",
                "arguments": "not-json",
                "call_id": "call_bad",
            }
        ],
        "usage": {},
    }
    result = model._parse_response(response)
    msg = result.generations[0].message
    assert len(msg.tool_calls) == 0
    assert len(msg.invalid_tool_calls) == 1
    assert msg.invalid_tool_calls[0]["name"] == "bad_tool"


# ---------------------------------------------------------------------------
# \u6b64\u5904\u8bf4\u660e\u8be5\u6d4b\u8bd5\u6bb5\u7684\u524d\u7f6e\u6761\u4ef6\u3001\u8c03\u7528\u9650\u5236\u53ca\u9884\u671f\u8fb9\u754c\u3002
# ---------------------------------------------------------------------------


def test_convert_messages_human():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    _, items = model._convert_messages([HumanMessage(content="Hello")])
    assert items == [{"role": "user", "content": "Hello"}]


def test_convert_messages_system_becomes_instructions():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    instructions, items = model._convert_messages([SystemMessage(content="You are helpful.")])
    assert "You are helpful." in instructions
    assert items == []


def test_convert_messages_ai_with_tool_calls():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "search", "args": {"q": "foo"}, "id": "tc1", "type": "tool_call"}],
    )
    _, items = model._convert_messages([ai])
    assert any(item.get("type") == "function_call" and item["name"] == "search" for item in items)


def test_convert_messages_tool_message():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc73\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    tool_msg = ToolMessage(content="result data", tool_call_id="tc1")
    _, items = model._convert_messages([tool_msg])
    assert items[0]["type"] == "function_call_output"
    assert items[0]["call_id"] == "tc1"
    assert items[0]["output"] == "result data"


# ---------------------------------------------------------------------------
# \u6b64\u5904\u8bf4\u660e\u8be5\u6d4b\u8bd5\u6bb5\u7684\u524d\u7f6e\u6761\u4ef6\u3001\u8c03\u7528\u9650\u5236\u53ca\u9884\u671f\u8fb9\u754c\u3002
# ---------------------------------------------------------------------------


def test_parse_sse_data_line_valid():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    from deerflow.models.openai_codex_provider import CodexChatModel

    data = {"type": "response.completed", "response": {}}
    line = "data: " + json.dumps(data)
    assert CodexChatModel._parse_sse_data_line(line) == data


def test_parse_sse_data_line_done_returns_none():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel._parse_sse_data_line("data: [DONE]") is None


def test_parse_sse_data_line_non_data_returns_none():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel._parse_sse_data_line("event: ping") is None


def test_parse_sse_data_line_invalid_json_returns_none():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel._parse_sse_data_line("data: {bad json}") is None


# ---------------------------------------------------------------------------
# \u6b64\u5904\u8bf4\u660e\u8be5\u6d4b\u8bd5\u6bb5\u7684\u524d\u7f6e\u6761\u4ef6\u3001\u8c03\u7528\u9650\u5236\u53ca\u9884\u671f\u8fb9\u754c\u3002
# ---------------------------------------------------------------------------


def test_parse_tool_call_arguments_valid_string():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": '{"key": "val"}', "name": "t", "call_id": "c"})
    assert parsed == {"key": "val"}
    assert err is None


def test_parse_tool_call_arguments_already_dict():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": {"key": "val"}, "name": "t", "call_id": "c"})
    assert parsed == {"key": "val"}
    assert err is None


def test_parse_tool_call_arguments_invalid_json():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc73\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": "not-json", "name": "t", "call_id": "c"})
    assert parsed is None
    assert err is not None
    assert "Failed to parse" in err["error"]


def test_parse_tool_call_arguments_non_dict_json():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc72\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": '["list", "not", "dict"]', "name": "t", "call_id": "c"})
    assert parsed is None
    assert err is not None
