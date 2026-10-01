'''

将 LangChain 消息对象转换为 OpenAI Chat Completions 格式的纯函数。
当前 RunJournal 仍直接调用 message.model_dump()；本模块供需要 OpenAI
线协议格式的调用方复用。
'''

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
    '''

    将单个 LangChain BaseMessage 转换为 OpenAI 消息字典。

        支持以下消息类型：
        - HumanMessage → {"role": "user", "content": "..."}
        - AIMessage (text only) → {"role": "assistant", "content": "..."}
        - AIMessage (with tool_calls) → {"role": "assistant", "content": null, "tool_calls": [...]}
        - AIMessage (text + tool_calls) → both content and tool_calls present
        - AIMessage (list content / multimodal) → content preserved as list
        - SystemMessage → {"role": "system", "content": "..."}
        - ToolMessage → {"role": "tool", "tool_call_id": "...", "content": "..."}
    '''
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
            result["content"] = content if (isinstance(content, list) and content) or (isinstance(content, str) and content) else None
            result["tool_calls"] = openai_tool_calls
        else:
            result["content"] = content

        return result

    return {"role": role, "content": content}


def _infer_finish_reason(message: Any) -> str:
    '''

    从 AIMessage 推断 OpenAI 的 finish_reason。

        存在 tool_calls 时返回 ``tool_calls``；否则读取
        response_metadata.finish_reason，最终回退为 ``stop``。
    '''
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
    '''

    将 AIMessage 及其元数据转换为 OpenAI completion 响应字典。

        返回结构：
            {
                "id": message.id,
                "model": message.response_metadata.get("model_name"),
                "choices": [{"index": 0, "message": <openai_message>, "finish_reason": <inferred>}],
                "usage": {"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...} or None,
            }
    '''
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
    '''

    将 LangChain BaseMessage 列表转换为 OpenAI 消息字典列表。'''
    return [langchain_to_openai_message(m) for m in messages]
