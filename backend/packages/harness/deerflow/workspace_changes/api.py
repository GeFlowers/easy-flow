'''从运行事件存储中恢复工作区变化，并按接口参数隐藏文件详情或差异。'''

from __future__ import annotations

from typing import Any

from .types import WORKSPACE_CHANGES_EVENT_TYPE, WORKSPACE_CHANGES_METADATA_KEY

EMPTY_SUMMARY = {
    "created": 0,
    "modified": 0,
    "deleted": 0,
    "additions": 0,
    "deletions": 0,
    "truncated": False,
}


async def get_workspace_changes_response(
    event_store: Any,
    thread_id: str,
    run_id: str,
    *,
    include_files: bool = True,
    include_diff: bool = True,
) -> dict[str, Any]:
    '''读取一次运行最新的工作区变化事件，返回可供前端展示的结构。'''
    events = await event_store.list_events(
        thread_id,
        run_id,
        event_types=[WORKSPACE_CHANGES_EVENT_TYPE],
        limit=10,
    )
    if not events:
        return _empty_response()

    payload = _extract_workspace_changes_payload(events[-1])
    if not isinstance(payload, dict):
        return _empty_response()

    response = dict(payload)
    response["available"] = True
    response.setdefault("summary", dict(EMPTY_SUMMARY))
    if include_files:
        response.setdefault("files", [])
        if not include_diff:
            response["files"] = [_without_diff(file) for file in response["files"]]
    else:
        response["files"] = []
    return response


def _empty_response() -> dict[str, Any]:
    '''构造尚无工作区变化事件时使用的稳定空响应。'''
    return {
        "available": False,
        "version": 1,
        "summary": dict(EMPTY_SUMMARY),
        "files": [],
        "limits": {},
    }


def _extract_workspace_changes_payload(event: dict[str, Any]) -> Any:
    '''兼容事件元数据和旧式事件正文两种工作区变化载荷位置。'''
    metadata = event.get("metadata") or {}
    if isinstance(metadata, dict) and WORKSPACE_CHANGES_METADATA_KEY in metadata:
        return metadata[WORKSPACE_CHANGES_METADATA_KEY]
    content = event.get("content")
    if isinstance(content, dict):
        return content
    return None


def _without_diff(file: Any) -> Any:
    '''复制文件变化记录并清空差异文本，保留路径和摘要等元数据。'''
    if not isinstance(file, dict):
        return file
    sanitized = dict(file)
    sanitized["diff"] = ""
    return sanitized
