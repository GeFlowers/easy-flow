"""本模块覆盖适配的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage


def _make_model(**kwargs):
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.models.patched_stepfun import PatchedChatStepFun

    return PatchedChatStepFun(
        model="step-3.7-flash",
        api_key="test-key",
        base_url="https://api.stepfun.com/v1",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Basic properties
# ---------------------------------------------------------------------------


def test_is_lc_serializable_returns_true():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    from deerflow.models.patched_stepfun import PatchedChatStepFun

    assert PatchedChatStepFun.is_lc_serializable() is True


def test_lc_secrets_contains_stepfun_api_key_mapping():
    """验证接口在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    assert model.lc_secrets["api_key"] == "STEPFUN_API_KEY"
    assert model.lc_secrets["openai_api_key"] == "STEPFUN_API_KEY"


# ---------------------------------------------------------------------------
# _extract_reasoning helper
# ---------------------------------------------------------------------------


def test_extract_reasoning_from_dict_with_reasoning():
    """验证推理 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.models.patched_stepfun import _extract_reasoning

    assert _extract_reasoning({"reasoning": "thinking..."}) == "thinking..."


def test_extract_reasoning_from_dict_with_reasoning_content():
    """验证推理 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.models.patched_stepfun import _extract_reasoning

    assert _extract_reasoning({"reasoning_content": "thinking..."}) == "thinking..."


def test_extract_reasoning_prefers_reasoning_content_over_reasoning():
    """验证推理 推理 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.models.patched_stepfun import _extract_reasoning

    result = _extract_reasoning({"reasoning_content": "deepseek", "reasoning": "native"})
    assert result == "deepseek"


def test_extract_reasoning_missing_returns_sentinel():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    from deerflow.models.patched_stepfun import _MISSING, _extract_reasoning

    assert _extract_reasoning({}) is _MISSING
    assert _extract_reasoning({"reasoning": None}) is _MISSING


# ---------------------------------------------------------------------------
# Request payload replay (_get_request_payload)
# ---------------------------------------------------------------------------


def test_reasoning_content_injected_into_assistant_tool_call_message():
    """验证推理 工具 消息在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    human = HumanMessage(content="Check Beijing weather.")
    ai = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "I need to call the weather tool."},
    )
    payload_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_weather",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location":"Beijing"}'},
            }
        ],
    }
    base_payload = {
        "messages": [
            {"role": "user", "content": "Check Beijing weather."},
            payload_message,
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assert payload["messages"][1]["reasoning_content"] == "I need to call the weather tool."


def test_reasoning_content_is_noop_when_missing():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    human = HumanMessage(content="hello")
    ai = AIMessage(content="hi", additional_kwargs={})
    base_payload = {
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assert "reasoning_content" not in payload["messages"][1]


# ---------------------------------------------------------------------------
# Streaming reasoning capture (_convert_chunk_to_generation_chunk)
# ---------------------------------------------------------------------------


def test_convert_chunk_captures_reasoning_field():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    chunk = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"role": "assistant", "reasoning": "I need "}}]},
        AIMessageChunk,
        {},
    )

    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning_content"] == "I need "


def test_convert_chunk_captures_reasoning_content_field():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    chunk = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"role": "assistant", "reasoning_content": "I need "}}]},
        AIMessageChunk,
        {},
    )

    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning_content"] == "I need "


def test_convert_chunk_streams_reasoning_then_content():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    first = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"role": "assistant", "reasoning": "I need "}}]},
        AIMessageChunk,
        {},
    )
    second = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"reasoning": "a tool."}}]},
        AIMessageChunk,
        {},
    )
    answer = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"content": "Done."}, "finish_reason": "stop"}], "model": "step-3.7-flash"},
        AIMessageChunk,
        {},
    )

    assert first is not None
    assert second is not None
    assert answer is not None

    combined = first.message + second.message + answer.message
    assert combined.additional_kwargs["reasoning_content"] == "I need a tool."
    assert combined.content == "Done."


def test_convert_chunk_noop_when_no_reasoning():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    chunk = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"content": "Hello."}, "finish_reason": "stop"}], "model": "step-3.7-flash"},
        AIMessageChunk,
        {},
    )

    assert chunk is not None
    assert "reasoning_content" not in chunk.message.additional_kwargs


# ---------------------------------------------------------------------------
# Non-streaming reasoning capture (_create_chat_result)
# ---------------------------------------------------------------------------


def test_create_chat_result_extracts_reasoning_field():
    """验证创建 结果 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "The weather is sunny.",
                    "reasoning": "The tool returned sunny weather.",
                },
                "finish_reason": "stop",
            }
        ],
        "model": "step-3.7-flash",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "The weather is sunny."
    assert message.additional_kwargs["reasoning_content"] == "The tool returned sunny weather."


def test_create_chat_result_extracts_reasoning_content_field():
    """验证创建 结果 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "The weather is sunny.",
                    "reasoning_content": "The tool returned sunny weather.",
                },
                "finish_reason": "stop",
            }
        ],
        "model": "step-3.7-flash",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "The weather is sunny."
    assert message.additional_kwargs["reasoning_content"] == "The tool returned sunny weather."


def test_create_chat_result_reads_reasoning_from_sdk_object():
    """验证创建 结果 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    class FakeMessage:
        """集中覆盖当前测试分支与回归边界。"""
        reasoning = "Reasoning stored on the SDK message object."
        reasoning_content = None
        model_extra = None

    class FakeChoice:
        """集中覆盖当前测试分支与回归边界。"""
        message = FakeMessage()

    class FakeResponse:
        """集中覆盖当前测试分支与回归边界。"""
        choices = [FakeChoice()]

        def model_dump(self, **kwargs):
            """处理模型相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Answer.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "model": "step-3.7-flash",
            }

    result = model._create_chat_result(FakeResponse())
    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "Reasoning stored on the SDK message object."


def test_create_chat_result_noop_when_no_reasoning():
    """验证创建 结果 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                },
                "finish_reason": "stop",
            }
        ],
        "model": "step-3.7-flash",
    }

    result = model._create_chat_result(response)
    assert "reasoning_content" not in result.generations[0].message.additional_kwargs
