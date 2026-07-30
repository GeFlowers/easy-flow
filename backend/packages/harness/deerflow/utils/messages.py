"""处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from langchain_core.messages import HumanMessage

ORIGINAL_USER_CONTENT_KEY = "original_user_content"
SUMMARY_MESSAGE_NAME = "summary"


def message_content_to_text(content: Any) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def message_to_text(message: Any, *, text_attribute_fallback: bool = False) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    nested = block.get("content")
                    if isinstance(nested, str):
                        parts.append(nested)
        return "".join(parts)
    if isinstance(content, Mapping):
        for key in ("text", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    if text_attribute_fallback:
        text = getattr(message, "text", None)
        if isinstance(text, str):
            return text
    return ""


def get_original_user_content_text(content: Any, additional_kwargs: Mapping[str, Any] | None) -> str:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    original_content = (additional_kwargs or {}).get(ORIGINAL_USER_CONTENT_KEY)
    if isinstance(original_content, str):
        return original_content
    return message_content_to_text(content)


def restore_original_human_message(message: HumanMessage) -> HumanMessage:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    original_content = message.additional_kwargs.get(ORIGINAL_USER_CONTENT_KEY)
    if not isinstance(original_content, str):
        return message

    additional_kwargs = dict(message.additional_kwargs)
    additional_kwargs.pop(ORIGINAL_USER_CONTENT_KEY, None)

    content = message.content
    if isinstance(content, str):
        restored_content: str | list = original_content
    elif isinstance(content, list):
        restored_content = []
        restored_text = False
        for block in content:
            is_string_text = isinstance(block, str)
            is_mapping_text = isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str)
            if not is_string_text and not is_mapping_text:
                restored_content.append(block)
                continue
            if restored_text:
                continue
            if is_mapping_text:
                restored_content.append({**block, "text": original_content})
            else:
                restored_content.append(original_content)
            restored_text = True
        if not restored_text:
            restored_content.insert(0, {"type": "text", "text": original_content})
    else:
        restored_content = original_content

    return message.model_copy(
        update={
            # Pydantic deep-copies the original model for ``deep=True``, but
            # applies values supplied through ``update`` without copying them.
            # Keep the persisted/UI copy fully isolated from the model-facing
            # message, including nested image/file blocks and metadata.
            "content": deepcopy(restored_content),
            "additional_kwargs": deepcopy(additional_kwargs),
        },
        deep=True,
    )


def is_real_user_message(message: object) -> bool:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    if not isinstance(message, HumanMessage):
        return False
    if message.name == SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui"):
        return False
    return True
