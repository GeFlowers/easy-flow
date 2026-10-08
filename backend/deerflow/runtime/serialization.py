'''

统一序列化 LangChain／LangGraph 对象。

提供统一的转换逻辑，将 LangChain 消息对象、Pydantic 模型及 LangGraph
状态字典转换为可用 JSON 序列化的普通 Python 数据结构。

调用方：``deerflow.runtime.runs.worker``（发布服务端推送事件）及
``app.gateway.routers.conversations.threads``（返回接口响应）。
'''

from __future__ import annotations

from typing import Any


def serialize_lc_object(obj: Any) -> Any:
    '''

    递归把 LangChain 消息及相关对象转换为可传输的 JSON 数据。'''
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: serialize_lc_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(item) for item in obj]
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
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
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def serialize_channel_values(channel_values: dict[str, Any]) -> dict[str, Any]:
    '''

    序列化通道值，并移除 LangGraph 内部键。

        仅移除 ``__pregel_*`` 键；保留 ``__interrupt__``，使 LangGraph
        客户端开发工具包可从 values 数据块中识别中断事件（见问题 #3595）。
    '''
    result: dict[str, Any] = {}
    for key, value in channel_values.items():
        if key.startswith("__pregel_"):
            continue
        result[key] = serialize_lc_object(value)
    return result


def strip_data_url_image_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    '''

    从隐藏消息中移除内嵌 data URL 图片，避免向界面暴露大块图像数据。

        历史记录和运行等待接口会向前端返回检查点中持久化的消息。
        ``ViewImageMiddleware`` 将完整 base64 图像数据保存在带有
        ``hide_from_ui`` 标记的用户消息中；这些数据属于模型内部上下文，
        不应通过网络发送，以免响应体过大且无法用于界面展示。

        仅移除类型为 ``image_url`` 且地址以 ``data:`` 开头的内容块。
        文本块、``https://`` 图片地址及未隐藏的消息保持原样，
        因而消息顺序和数量不变。
    '''
    result: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            result.append(msg)
            continue

        additional_kwargs = msg.get("additional_kwargs")
        if not (isinstance(additional_kwargs, dict) and additional_kwargs.get("hide_from_ui") is True):
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue

        filtered = [block for block in content if not (isinstance(block, dict) and block.get("type") == "image_url" and isinstance(block.get("image_url"), dict) and str(block["image_url"].get("url", "")).startswith("data:"))]
        result.append({**msg, "content": filtered})
    return result


def serialize_channel_values_for_api(channel_values: dict[str, Any]) -> dict[str, Any]:
    '''

    序列化通道值，并从消息中移除 base64 图像数据。

        合并 :func:`serialize_channel_values` 与
        :func:`strip_data_url_image_blocks` 的便捷封装。所有向前端返回通道值的
        接口均应使用它，避免通过网络发送采用 ``data:`` 方案的 base64 图像数据。
    '''
    result = serialize_channel_values(channel_values)
    if isinstance(result.get("messages"), list):
        result["messages"] = strip_data_url_image_blocks(result["messages"])
    return result


def serialize_messages_tuple(obj: Any) -> Any:
    '''

    序列化 messages 模式的元组 ``(chunk, metadata)``。'''
    if isinstance(obj, tuple) and len(obj) == 2:
        chunk, metadata = obj
        return [serialize_lc_object(chunk), metadata if isinstance(metadata, dict) else {}]
    return serialize_lc_object(obj)


def serialize(obj: Any, *, mode: str = "") -> Any:
    '''

    根据流模式序列化 LangChain 对象。

        * ``messages`` — obj 为 ``(message_chunk, metadata_dict)``。
        * ``values`` — obj 为完整状态字典；移除 ``__pregel_*`` 键，
          并从 hide_from_ui 消息中移除 base64 ``data:`` 图像块。
        * 其他模式 — 递归转换，并回退调用 ``model_dump()``／``dict()``。
    '''
    if mode == "messages":
        return serialize_messages_tuple(obj)
    if mode == "values":
        return serialize_channel_values_for_api(obj) if isinstance(obj, dict) else serialize_lc_object(obj)
    return serialize_lc_object(obj)
