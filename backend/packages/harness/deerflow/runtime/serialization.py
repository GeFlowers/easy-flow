'定义 serialization 模块提供的职责与可复用接口。\n\nCanonical serialization for LangChain / LangGraph objects.\n\nProvides a single source of truth for converting LangChain message\nobjects, Pydantic models, and LangGraph state dicts into plain\nJSON-serialisable Python structures.\n\nConsumers: ``deerflow.runtime.runs.worker`` (SSE publishing) and\n``app.gateway.routers.threads`` (REST responses).\n'

from __future__ import annotations

from typing import Any


def serialize_lc_object(obj: Any) -> Any:
    '执行 serialize_lc_object 的明确职责，并返回与调用约定一致的结果。\n\nRecursively serialize a LangChain object to a JSON-serialisable dict.'
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: serialize_lc_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(item) for item in obj]
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    # Pydantic v1 / older objects
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    # Interrupt is a __slots__ class — no model_dump/dict/__dict__, so it
    # would reach str() and produce a malformed payload.
    try:
        from langgraph.types import Interrupt
    except ImportError:
        pass
    else:
        if isinstance(obj, Interrupt):
            return serialize_lc_object(
                {
                    "value": obj.value,
                    "id": getattr(obj, "id", None),
                }
            )
    # Last resort
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def serialize_channel_values(channel_values: dict[str, Any]) -> dict[str, Any]:
    '执行 serialize_channel_values 的明确职责，并返回与调用约定一致的结果。\n\nSerialize channel values, stripping internal LangGraph keys.\n\n    Only ``__pregel_*`` keys are removed — ``__interrupt__`` is deliberately\n    preserved so the LangGraph SDK can detect interrupt events from values\n    chunks (see issue #3595).\n    '
    result: dict[str, Any] = {}
    for key, value in channel_values.items():
        if key.startswith("__pregel_"):
            continue
        result[key] = serialize_lc_object(value)
    return result


def strip_data_url_image_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    '执行 strip_data_url_image_blocks 的明确职责，并返回与调用约定一致的结果。\n\nRemove ``data:``-scheme ``image_url`` blocks from *hide_from_ui* messages.\n\n    The history and run-wait endpoints return checkpoint-persisted messages to\n    the frontend.  ``ViewImageMiddleware`` stores full base64 image payloads in\n    ``hide_from_ui`` human messages — these are internal model context and must\n    not be sent over the wire (huge response bodies, no UI value).\n\n    Only content blocks of type ``image_url`` whose URL starts with ``data:``\n    are stripped.  Text blocks, ``https://`` image URLs, and non-hidden\n    messages are left untouched so that message ordering and count are\n    preserved.\n    '
    result: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            result.append(msg)
            continue

        # Only touch messages explicitly flagged as hidden from the UI.
        additional_kwargs = msg.get("additional_kwargs")
        if not (isinstance(additional_kwargs, dict) and additional_kwargs.get("hide_from_ui") is True):
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue

        # Filter out image_url blocks with data: scheme.
        filtered = [block for block in content if not (isinstance(block, dict) and block.get("type") == "image_url" and isinstance(block.get("image_url"), dict) and str(block["image_url"].get("url", "")).startswith("data:"))]
        result.append({**msg, "content": filtered})
    return result


def serialize_channel_values_for_api(channel_values: dict[str, Any]) -> dict[str, Any]:
    '执行 serialize_channel_values_for_api 的明确职责，并返回与调用约定一致的结果。\n\nSerialize channel values and strip base64 image data from messages.\n\n    Convenience wrapper combining :func:`serialize_channel_values` with\n    :func:`strip_data_url_image_blocks`.  Use this in all REST endpoints\n    that return channel values to the frontend so that ``data:``-scheme\n    base64 image payloads are never sent over the wire.\n    '
    result = serialize_channel_values(channel_values)
    if isinstance(result.get("messages"), list):
        result["messages"] = strip_data_url_image_blocks(result["messages"])
    return result


def serialize_messages_tuple(obj: Any) -> Any:
    '执行 serialize_messages_tuple 的明确职责，并返回与调用约定一致的结果。\n\nSerialize a messages-mode tuple ``(chunk, metadata)``.'
    if isinstance(obj, tuple) and len(obj) == 2:
        chunk, metadata = obj
        return [serialize_lc_object(chunk), metadata if isinstance(metadata, dict) else {}]
    return serialize_lc_object(obj)


def serialize(obj: Any, *, mode: str = "") -> Any:
    '执行 serialize 的明确职责，并返回与调用约定一致的结果。\n\nSerialize LangChain objects with mode-specific handling.\n\n    * ``messages`` — obj is ``(message_chunk, metadata_dict)``\n    * ``values`` — obj is the full state dict; ``__pregel_*`` keys stripped and\n      base64 ``data:`` image blocks dropped from hide_from_ui messages\n    * everything else — recursive ``model_dump()`` / ``dict()`` fallback\n    '
    if mode == "messages":
        return serialize_messages_tuple(obj)
    if mode == "values":
        # ``values`` snapshots stream the full state to the frontend, so they
        # must drop base64 image payloads the same way the REST endpoints do.
        return serialize_channel_values_for_api(obj) if isinstance(obj, dict) else serialize_lc_object(obj)
    return serialize_lc_object(obj)
