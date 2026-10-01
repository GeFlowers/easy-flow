'''为 Langfuse 追踪补充会话、用户、模型、环境和 DeerFlow 请求关联标识。'''

from __future__ import annotations

from typing import Any

from deerflow.config import get_enabled_tracing_providers
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, normalize_trace_id

# 延迟导入运行时用户上下文，避免 runtime 加载运行工作器时反向导入 tracing 形成循环依赖。
_DEFAULT_TRACE_NAME = "lead-agent"


def build_langfuse_trace_metadata(
    *,
    thread_id: str | None,
    user_id: str | None = None,
    assistant_id: str | None = None,
    model_name: str | None = None,
    environment: str | None = None,
    deerflow_trace_id: str | None = None,
) -> dict[str, Any]:
    '''追踪启用时生成 Langfuse 元数据；关闭时返回空字典，不影响普通调用。'''
    if "langfuse" not in get_enabled_tracing_providers():
        return {}

    from deerflow.runtime.user_context import DEFAULT_USER_ID

    metadata: dict[str, Any] = {
        "langfuse_session_id": thread_id,
        "langfuse_user_id": user_id or DEFAULT_USER_ID,
        "langfuse_trace_name": assistant_id or _DEFAULT_TRACE_NAME,
    }
    request_trace_id = normalize_trace_id(deerflow_trace_id) or get_current_trace_id()
    if request_trace_id:
        metadata[DEERFLOW_TRACE_METADATA_KEY] = request_trace_id

    tags: list[str] = []
    if environment:
        tags.append(f"env:{environment}")
    if model_name:
        tags.append(f"model:{model_name}")
    if tags:
        metadata["langfuse_tags"] = tags

    return metadata


def inject_langfuse_metadata(
    config: dict,
    *,
    thread_id: str | None,
    user_id: str | None = None,
    assistant_id: str | None = None,
    model_name: str | None = None,
    environment: str | None = None,
    deerflow_trace_id: str | None = None,
) -> None:
    '''将生成的 Langfuse 元数据合并进调用配置，保留调用方显式设置的值。'''
    langfuse_metadata = build_langfuse_trace_metadata(
        thread_id=thread_id,
        user_id=user_id,
        assistant_id=assistant_id,
        model_name=model_name,
        environment=environment,
        deerflow_trace_id=deerflow_trace_id,
    )
    if not langfuse_metadata:
        return

    merged_metadata = dict(config.get("metadata") or {})
    for key, value in langfuse_metadata.items():
        merged_metadata.setdefault(key, value)
    config["metadata"] = merged_metadata
