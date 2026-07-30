"""覆盖本文件测试的输入约束、模拟边界与回归保护，确保测试仅记录既有行为。"""

from deerflow.agents.human_input import read_human_input_response


def _text_response(value: str):
    """构造测试所需的受控前置条件，隔离外部资源并保持断言可重复。"""
    return {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "clarification:call-abc",
        "response_kind": "text",
        "value": value,
    }


def test_read_human_input_response_requires_non_empty_value():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    assert read_human_input_response({"human_input_response": _text_response("")}) is None
    assert read_human_input_response({"human_input_response": _text_response("   ")}) is None


def test_read_human_input_response_preserves_non_empty_value():
    """验证当前用例覆盖的既有输入、返回或异常契约；生产实现偏离时，本用例必须明确失败。"""
    response = read_human_input_response({"human_input_response": _text_response(" staging ")})

    assert response is not None
    assert response["value"] == " staging "
