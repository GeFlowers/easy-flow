'''将工具结果和异常归一为结构化状态，供进度展示及后续策略判断复用。'''

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import ToolMessage
from langgraph.types import Command

TOOL_META_KEY = "deerflow_tool_meta"

_ERROR_PREFIX = "Error:"
_PARTIAL_MARKERS = (
    "partial results",
    "limited results",
    "truncated",
    "results may be incomplete",
    "no results found",
    "no content found",
    "no images found",
)


@dataclass(frozen=True, slots=True)
class ToolResultMeta:
    '''描述工具执行状态、错误类型、模型可恢复性、建议后续动作及状态来源。'''

    status: Literal["success", "error", "partial_success"]
    error_type: str | None
    recoverable_by_model: bool
    recommended_next_action: Literal["continue", "rewrite_query", "try_alternative", "summarize", "stop"]
    source: Literal["exception", "tool_return", "content_analysis", "progress_middleware"]


_ERROR_RULES: list[tuple[list[str], dict[str, object]]] = [
    (
        ["401", "403", "unauthorized", "authentication", "invalid api key"],
        {"error_type": "auth", "recoverable_by_model": False, "recommended_next_action": "stop"},
    ),
    (
        ["rate limit", "rate limited", "rate_limit"],
        {"error_type": "rate_limited", "recoverable_by_model": False, "recommended_next_action": "summarize"},
    ),
    (
        ["timeout", "timed out", "connection", "network error", "temporarily unavailable"],
        {"error_type": "transient", "recoverable_by_model": False, "recommended_next_action": "try_alternative"},
    ),
    (
        ["not configured", "not installed", "missing required", "disabled", "no api key"],
        {"error_type": "config", "recoverable_by_model": False, "recommended_next_action": "stop"},
    ),
    (
        ["permission denied", "access denied", "path traversal", "forbidden"],
        {"error_type": "permission", "recoverable_by_model": True, "recommended_next_action": "try_alternative"},
    ),
    (
        ["no results found", "no content found", "no images found", "no results"],
        {"error_type": "no_results", "recoverable_by_model": True, "recommended_next_action": "rewrite_query"},
    ),
    (
        ["not found", "no such file", "does not exist", "404"],
        {"error_type": "not_found", "recoverable_by_model": True, "recommended_next_action": "rewrite_query"},
    ),
    (
        ["unexpected error", "internal error", "500"],
        {"error_type": "internal", "recoverable_by_model": False, "recommended_next_action": "stop"},
    ),
]

_UNKNOWN_ERROR: dict[str, object] = {
    "error_type": "unknown",
    "recoverable_by_model": True,
    "recommended_next_action": "try_alternative",
}

_NUMERIC_KW_RE: dict[str, re.Pattern[str]] = {kw: re.compile(rf"\b{kw}\b") for rule_keywords, _ in _ERROR_RULES for kw in rule_keywords if kw.isdigit()}

_SEMANTIC_ZERO_ERROR_STRINGS: frozenset[str] = frozenset({"none", "null", "false", "no", "ok", "success", "n/a", ""})


def _extract_json_error_text(content: str) -> str | None:
    '''仅提取 JSON 对象中的 error 字段，并忽略通常表示成功的空值和哨兵文本。'''
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    error = data.get("error") if isinstance(data, dict) else None
    if not error:
        return None
    if isinstance(error, str) and error.lower().strip() in _SEMANTIC_ZERO_ERROR_STRINGS:
        return None
    return error if isinstance(error, str) else json.dumps(error)


def _match_keyword(kw: str, lower: str) -> bool:
    '''按规则匹配错误关键词；纯数字状态码使用单词边界，避免命中普通数值片段。'''
    if kw.isdigit():
        return bool(_NUMERIC_KW_RE[kw].search(lower))
    return kw in lower


def _classify_error_text(text: str) -> dict[str, object]:
    '''按错误规则表识别认证、配额、网络、配置、权限等类别及建议动作。'''
    lower = text.lower()
    for keywords, attrs in _ERROR_RULES:
        if any(_match_keyword(kw, lower) for kw in keywords):
            return {**attrs}
    return {**_UNKNOWN_ERROR}


def _make_meta(*, status: str, source: str, error_type: str | None = None, recoverable_by_model: bool = True, recommended_next_action: str = "continue") -> dict[str, object]:
    '''构造统一的工具结果元数据字段，并允许调用方指定状态、错误来源和恢复建议。'''
    return {
        "status": status,
        "error_type": error_type,
        "recoverable_by_model": recoverable_by_model,
        "recommended_next_action": recommended_next_action,
        "source": source,
    }


def stamp_exception_meta(msg: ToolMessage, exc_info: str) -> ToolMessage:
    '''根据异常详情分类并覆盖工具消息上的旧元数据，以异常处理结果作为最终判定。'''
    attrs = _classify_error_text(exc_info)
    updated_kwargs = dict(msg.additional_kwargs or {})
    updated_kwargs[TOOL_META_KEY] = _make_meta(status="error", source="exception", **attrs)
    msg.additional_kwargs = updated_kwargs
    return msg


def normalize_tool_message(msg: ToolMessage) -> ToolMessage:
    '''保留已有元数据；否则根据错误状态、JSON 错误字段和部分结果提示标记消息。'''
    existing = (msg.additional_kwargs or {}).get(TOOL_META_KEY)
    if existing is not None:
        return msg

    content = msg.content if isinstance(msg.content, str) else ""
    content_lower = content.lower()

    if msg.status == "error" and not content.startswith(_ERROR_PREFIX):
        json_error = _extract_json_error_text(content)
        if json_error is not None:
            attrs = _classify_error_text(json_error)
        else:
            try:
                is_json_dict = isinstance(json.loads(content), dict)
            except (json.JSONDecodeError, ValueError):
                is_json_dict = False
            attrs = {**_UNKNOWN_ERROR} if is_json_dict else _classify_error_text(content)
        meta = _make_meta(status="error", source="tool_return", **attrs)
    elif content.startswith(_ERROR_PREFIX):
        attrs = _classify_error_text(content[len(_ERROR_PREFIX) :])
        meta = _make_meta(status="error", source="tool_return", **attrs)
    elif (json_error := _extract_json_error_text(content)) is not None:
        attrs = _classify_error_text(json_error)
        meta = _make_meta(status="error", source="tool_return", **attrs)
    elif any(m in content_lower for m in _PARTIAL_MARKERS):
        meta = _make_meta(
            status="partial_success",
            source="content_analysis",
            recommended_next_action="rewrite_query",
        )
    else:
        meta = _make_meta(status="success", source="content_analysis")

    updated_kwargs = dict(msg.additional_kwargs or {})
    updated_kwargs[TOOL_META_KEY] = meta
    msg.additional_kwargs = updated_kwargs
    return msg


def normalize_tool_result(result: ToolMessage | Command) -> ToolMessage | Command:
    '''规范化直接返回的工具消息；对包含状态更新命令的结果保持原样。'''
    if isinstance(result, ToolMessage):
        return normalize_tool_message(result)
    return result
