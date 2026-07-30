"""本模块覆盖适配的行为、边界与回归场景，确保既有契约稳定。"""

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from deerflow.models.patched_minimax import PatchedChatMiniMax


def _make_model(**kwargs) -> PatchedChatMiniMax:
    """准备可控测试资源与状态，供后续断言读取。"""
    return PatchedChatMiniMax(
        model="MiniMax-M3",
        api_key="test-key",
        base_url="https://example.com/v1",
        **kwargs,
    )


def test_get_request_payload_preserves_thinking_and_forces_reasoning_split():
    """验证获取 请求 载荷 思考 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model(extra_body={"thinking": {"type": "disabled"}})

    payload = model._get_request_payload([HumanMessage(content="hello")])

    assert payload["extra_body"]["thinking"]["type"] == "disabled"
    assert payload["extra_body"]["reasoning_split"] is True


def test_get_request_payload_strips_inconsistent_user_message_names():
    """验证获取 请求 载荷 用户 消息在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()

    payload = model._get_request_payload(
        [
            SystemMessage(content="system"),
            HumanMessage(content="older summary", name="summary"),
            AIMessage(content="ok"),
            HumanMessage(content="latest question", name="user-input"),
        ]
    )

    user_messages = [m for m in payload["messages"] if m["role"] == "user"]
    assert len(user_messages) == 2
    assert all(m.get("name") is None for m in user_messages)


def test_create_chat_result_maps_reasoning_details_to_reasoning_content():
    """验证创建 结果 推理 推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "最终答案",
                    "reasoning_details": [
                        {
                            "type": "reasoning.text",
                            "id": "reasoning-text-1",
                            "format": "MiniMax-response-v1",
                            "index": 0,
                            "text": "先分析问题，再给出答案。",
                        }
                    ],
                },
                "finish_reason": "stop",
            }
        ],
        "model": "MiniMax-M3",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "最终答案"
    assert message.additional_kwargs["reasoning_content"] == "先分析问题，再给出答案。"
    assert result.generations[0].text == "最终答案"


def test_create_chat_result_strips_inline_think_tags():
    """验证创建 结果在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "<think>\n这是思考过程。\n</think>\n\n真正回答。",
                },
                "finish_reason": "stop",
            }
        ],
        "model": "MiniMax-M3",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "真正回答。"
    assert message.additional_kwargs["reasoning_content"] == "这是思考过程。"
    assert result.generations[0].text == "真正回答。"


def test_convert_chunk_to_generation_chunk_preserves_reasoning_deltas():
    """验证推理在预期条件及边界场景下的可观察行为，防止相关回归。"""
    model = _make_model()
    first = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_details": [
                            {
                                "type": "reasoning.text",
                                "id": "reasoning-text-1",
                                "format": "MiniMax-response-v1",
                                "index": 0,
                                "text": "The user",
                            }
                        ],
                    }
                }
            ]
        },
        AIMessageChunk,
        {},
    )
    second = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "content": "",
                        "reasoning_details": [
                            {
                                "type": "reasoning.text",
                                "id": "reasoning-text-1",
                                "format": "MiniMax-response-v1",
                                "index": 0,
                                "text": " asks.",
                            }
                        ],
                    }
                }
            ]
        },
        AIMessageChunk,
        {},
    )
    answer = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "content": "最终答案",
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": "MiniMax-M3",
        },
        AIMessageChunk,
        {},
    )

    assert first is not None
    assert second is not None
    assert answer is not None

    combined = first.message + second.message + answer.message

    assert combined.additional_kwargs["reasoning_content"] == "The user asks."
    assert combined.content == "最终答案"
