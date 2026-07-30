'定义 converters 模块提供的职责与可复用接口。\n\nPure functions to convert LangChain message objects to OpenAI Chat Completions format.\n\nUtility for translating LangChain message types to OpenAI-compatible dicts.\nNot currently wired into RunJournal (which uses message.model_dump() directly),\nbut available for consumers that need the OpenAI wire format.\n'

from __future__ import annotations

import json
from typing import Any

_ROLE_MAP = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
}


def langchain_to_openai_message(message: Any) -> dict:
    '执行 langchain_to_openai_message 的明确职责，并返回与调用约定一致的结果。\n\nConvert a single LangChain BaseMessage to an OpenAI message dict.\n\n    Handles:\n    - HumanMessage → {"role": "user", "content": "..."}\n    - AIMessage (text only) → {"role": "assistant", "content": "..."}\n    - AIMessage (with tool_calls) → {"role": "assistant", "content": null, "tool_calls": [...]}\n    - AIMessage (text + tool_calls) → both content and tool_calls present\n    - AIMessage (list content / multimodal) → content preserved as list\n    - SystemMessage → {"role": "system", "content": "..."}\n    - ToolMessage → {"role": "tool", "tool_call_id": "...", "content": "..."}\n    '
    msg_type = getattr(message, "type", "")
    role = _ROLE_MAP.get(msg_type, msg_type)
    content = getattr(message, "content", "")

    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": getattr(message, "tool_call_id", ""),
            "content": content,
        }

    if role == "assistant":
        tool_calls = getattr(message, "tool_calls", None) or []
        result: dict = {"role": "assistant"}

        if tool_calls:
            openai_tool_calls = []
            for tc in tool_calls:
                args = tc.get("args", {})
                openai_tool_calls.append(
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(args) if not isinstance(args, str) else args,
                        },
                    }
                )
            # If no text content, set content to null per OpenAI spec
            result["content"] = content if (isinstance(content, list) and content) or (isinstance(content, str) and content) else None
            result["tool_calls"] = openai_tool_calls
        else:
            result["content"] = content

        return result

    # user / system / unknown
    return {"role": role, "content": content}


def _infer_finish_reason(message: Any) -> str:
    '执行 _infer_finish_reason 的明确职责，并返回与调用约定一致的结果。\n\nInfer OpenAI finish_reason from an AIMessage.\n\n    Returns "tool_calls" if tool_calls present, else looks in\n    response_metadata.finish_reason, else returns "stop".\n    '
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        return "tool_calls"
    resp_meta = getattr(message, "response_metadata", None) or {}
    if isinstance(resp_meta, dict):
        finish = resp_meta.get("finish_reason")
        if finish:
            return finish
    return "stop"


def langchain_to_openai_completion(message: Any) -> dict:
    '执行 langchain_to_openai_completion 的明确职责，并返回与调用约定一致的结果。\n\nConvert an AIMessage and its metadata to an OpenAI completion response dict.\n\n    Returns:\n        {\n            "id": message.id,\n            "model": message.response_metadata.get("model_name"),\n            "choices": [{"index": 0, "message": <openai_message>, "finish_reason": <inferred>}],\n            "usage": {"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...} or None,\n        }\n    '
    resp_meta = getattr(message, "response_metadata", None) or {}
    model_name = resp_meta.get("model_name") if isinstance(resp_meta, dict) else None

    openai_msg = langchain_to_openai_message(message)
    finish_reason = _infer_finish_reason(message)

    usage_metadata = getattr(message, "usage_metadata", None)
    if usage_metadata is not None:
        input_tokens = usage_metadata.get("input_tokens", 0) or 0
        output_tokens = usage_metadata.get("output_tokens", 0) or 0
        usage: dict | None = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    else:
        usage = None

    return {
        "id": getattr(message, "id", None),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": openai_msg,
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def langchain_messages_to_openai(messages: list) -> list[dict]:
    '执行 langchain_messages_to_openai 的明确职责，并返回与调用约定一致的结果。\n\nConvert a list of LangChain BaseMessages to OpenAI message dicts.'
    return [langchain_to_openai_message(m) for m in messages]
