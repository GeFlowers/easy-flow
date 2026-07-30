"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.models.assistant_payload_replay import (
    restore_additional_kwargs_field,
    restore_assistant_payloads,
    restore_reasoning_content,
)


def _restore_reasoning(payload_msg: dict, orig_msg: AIMessage) -> None:
    """为“还原推理”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    restore_additional_kwargs_field(payload_msg, orig_msg, "reasoning_content")


def test_restore_additional_kwargs_field_copies_present_values_only():
    """验证“还原额外关键字参数该项该项该项该项仅”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    payload_message = {"role": "assistant"}
    orig_message = AIMessage(
        content="answer",
        additional_kwargs={
            "reasoning_content": "",
            "ignored_none": None,
        },
    )

    restore_additional_kwargs_field(payload_message, orig_message, "reasoning_content")
    restore_additional_kwargs_field(payload_message, orig_message, "ignored_none")
    restore_additional_kwargs_field(payload_message, orig_message, "missing")

    assert payload_message == {"role": "assistant", "reasoning_content": ""}


def test_restore_reasoning_content_copies_reasoning_content():
    """验证“还原推理内容该项推理内容”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    payload_message = {"role": "assistant"}
    orig_message = AIMessage(content="answer", additional_kwargs={"reasoning_content": "thought"})

    restore_reasoning_content(payload_message, orig_message)

    assert payload_message["reasoning_content"] == "thought"


def test_restore_assistant_payloads_matches_by_position_when_lengths_match():
    """验证“还原助手该项该项该项位置当该项匹配”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    original_messages = [
        HumanMessage(content="question"),
        AIMessage(content="answer", additional_kwargs={"reasoning_content": "thought"}),
    ]
    payload_messages = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[1]["reasoning_content"] == "thought"


def test_restore_assistant_payloads_fallback_matches_unique_content_signature():
    """验证“还原助手该项该项该项唯一内容签名”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    original_messages = [
        AIMessage(content="first", additional_kwargs={"reasoning_content": "first-thought"}),
        AIMessage(content="second", additional_kwargs={"reasoning_content": "second-thought"}),
    ]
    payload_messages = [{"role": "assistant", "content": "second"}]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "second-thought"


def test_restore_assistant_payloads_fallback_matches_unique_tool_call_signature():
    """验证“还原助手该项该项该项唯一工具该项签名”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    original_messages = [
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "first-thought"},
            tool_calls=[{"id": "call_first", "name": "tool", "args": {}}],
        ),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "second-thought"},
            tool_calls=[{"id": "call_second", "name": "tool", "args": {}}],
        ),
    ]
    payload_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_second", "type": "function", "function": {"name": "tool", "arguments": "{}"}}],
        }
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "second-thought"


def test_restore_assistant_payloads_fallback_matches_structured_content_signature():
    """验证“还原助手该项该项该项结构化内容签名”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    original_messages = [
        AIMessage(
            content=[{"type": "text", "text": "first"}],
            additional_kwargs={"reasoning_content": "first-thought"},
        ),
        AIMessage(
            content=[{"type": "text", "text": "second"}],
            additional_kwargs={"reasoning_content": "second-thought"},
        ),
    ]
    payload_messages = [{"role": "assistant", "content": [{"text": "second", "type": "text"}]}]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "second-thought"


def test_restore_assistant_payloads_fallback_uses_order_when_signature_is_ambiguous():
    """验证“还原助手该项该项使用该项当签名该项歧义”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    original_messages = [
        AIMessage(content="", additional_kwargs={"reasoning_content": "first-thought"}),
        AIMessage(content="", additional_kwargs={"reasoning_content": "second-thought"}),
    ]
    payload_messages = [{"role": "assistant", "content": ""}]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "first-thought"


def test_restore_assistant_payloads_fallback_uses_next_unused_when_ordinal_taken():
    # 序列化丢弃了前导的空辅助消息，因此有效负载序数
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 通过签名唯一匹配非序数索引，这使得后面的索引
    # 不明确的有效负载的确切序数索引已使用。一定还是会跌
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 而不是默默地删除该字段。
    """验证“还原助手该项该项使用下一个该项当该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    original_messages = [
        AIMessage(content="", additional_kwargs={"reasoning_content": "dropped-thought"}),
        AIMessage(content="unique", additional_kwargs={"reasoning_content": "unique-thought"}),
        AIMessage(content="", additional_kwargs={"reasoning_content": "trailing-thought"}),
    ]
    payload_messages = [
        {"role": "assistant", "content": "unique"},
        {"role": "assistant", "content": ""},
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "unique-thought"
    # 从所采取的序号中进行正向扫描会选择尾随消息，而不是
    # 删除了前导一项（天真的最小未使用扫描会错误地选择它）。
    assert payload_messages[1]["reasoning_content"] == "trailing-thought"


def test_restore_assistant_payloads_does_not_wrap_to_earlier_unused_message():
    """验证“还原助手该项该项该项该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    original_messages = [
        HumanMessage(content="leading user"),
        AIMessage(content="", additional_kwargs={"reasoning_content": "dropped-leading-thought"}),
        AIMessage(content="unique", additional_kwargs={"reasoning_content": "unique-thought"}),
    ]
    payload_messages = [
        {"role": "assistant", "content": "unique"},
        {"role": "assistant", "content": ""},
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "unique-thought"
    assert "reasoning_content" not in payload_messages[1]
