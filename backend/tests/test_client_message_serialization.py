"""\u672c\u6a21\u5757\u8986\u76d6\u76f8\u5173\u6d4b\u8bd5\uff0c\u56fa\u5b9a\u516c\u5f00\u884c\u4e3a\u3001\u5931\u8d25\u5904\u7406\u4e0e\u72b6\u6001\u8fb9\u754c\u3002"""

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.client import DeerFlowClient


def test_serialize_ai_message_preserves_additional_kwargs():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc73\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    message = AIMessage(
        content="done",
        additional_kwargs={
            "token_usage_attribution": {
                "version": 1,
                "kind": "final_answer",
                "shared_attribution": False,
                "actions": [],
            }
        },
        usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    )

    serialized = DeerFlowClient._serialize_message(message)

    assert serialized["type"] == "ai"
    assert serialized["usage_metadata"] == {
        "input_tokens": 12,
        "output_tokens": 3,
        "total_tokens": 15,
    }
    assert serialized["additional_kwargs"] == {
        "token_usage_attribution": {
            "version": 1,
            "kind": "final_answer",
            "shared_attribution": False,
            "actions": [],
        }
    }


def test_serialize_human_message_preserves_additional_kwargs():
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    message = HumanMessage(
        content="hello",
        additional_kwargs={"files": [{"name": "diagram.png"}]},
    )

    serialized = DeerFlowClient._serialize_message(message)

    assert serialized == {
        "type": "human",
        "content": "hello",
        "id": None,
        "additional_kwargs": {"files": [{"name": "diagram.png"}]},
    }
