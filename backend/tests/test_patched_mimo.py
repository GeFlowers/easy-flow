"""本模块覆盖适配的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage


def _make_model(**kwargs):
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.models.patched_mimo import PatchedChatMiMo

    return PatchedChatMiMo(
        model="mimo-v2.5-pro",
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        **kwargs,
    )


def test_is_lc_serializable_returns_true():
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    from deerflow.models.patched_mimo import PatchedChatMiMo

    assert PatchedChatMiMo.is_lc_serializable() is True


def test_lc_secrets_contains_mimo_api_key_mapping():
    """验证接口在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    assert model.lc_secrets["api_key"] == "MIMO_API_KEY"
    assert model.lc_secrets["openai_api_key"] == "MIMO_API_KEY"


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


def test_create_chat_result_maps_message_reasoning_content():
    """验证创建 结果 消息 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "The weather is sunny.",
                    "reasoning_content": "The tool returned sunny weather, so answer directly.",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "model": "mimo-v2.5-pro",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "The weather is sunny."
    assert message.additional_kwargs["reasoning_content"] == "The tool returned sunny weather, so answer directly."


def test_create_chat_result_reads_reasoning_content_from_message_attribute():
    """验证创建 结果 推理 消息在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    class FakeMessage:
        """集中覆盖当前测试分支与回归边界。"""
        reasoning_content = "Reasoning stored on the SDK message object."

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
                "model": "mimo-v2.5-pro",
            }

    result = model._create_chat_result(FakeResponse())

    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "Reasoning stored on the SDK message object."


def test_convert_chunk_to_generation_chunk_preserves_reasoning_deltas():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    first = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"role": "assistant", "reasoning_content": "I need "}}]},
        AIMessageChunk,
        {},
    )
    second = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"reasoning_content": "a tool."}}]},
        AIMessageChunk,
        {},
    )
    answer = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"content": "Done."}, "finish_reason": "stop"}], "model": "mimo-v2.5-pro"},
        AIMessageChunk,
        {},
    )

    assert first is not None
    assert second is not None
    assert answer is not None

    combined = first.message + second.message + answer.message

    assert combined.additional_kwargs["reasoning_content"] == "I need a tool."
    assert combined.content == "Done."
