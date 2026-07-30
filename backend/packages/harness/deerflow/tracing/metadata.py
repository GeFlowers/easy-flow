"""处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""

from __future__ import annotations

from typing import Any

from deerflow.config import get_enabled_tracing_providers
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, normalize_trace_id

# Lazy-imported below to avoid a circular import: ``deerflow.runtime`` eagerly
# imports the run worker, which in turn needs ``deerflow.tracing``.
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
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
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
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
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
