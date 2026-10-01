'''集中定义子代理结果状态、停止原因以及跨消息传递的元数据校验。'''

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Literal, NotRequired, TypedDict

SUBAGENT_STATUS_KEY = "subagent_status"
SUBAGENT_STOP_REASON_KEY = "subagent_stop_reason"
SUBAGENT_ERROR_KEY = "subagent_error"
SUBAGENT_RESULT_BRIEF_KEY = "subagent_result_brief"
SUBAGENT_RESULT_SHA256_KEY = "subagent_result_sha256"
SUBAGENT_MODEL_NAME_KEY = "subagent_model_name"
SUBAGENT_TOKEN_USAGE_KEY = "subagent_token_usage"
SUBAGENT_METADATA_TEXT_MAX_CHARS = 2000

#: 生产端写入 64 位小写 SHA-256 摘要；读取端校验格式，避免损坏的中继值被当作摘要。
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")

SubagentStatusValue = Literal[
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "polling_timed_out",
]

#: 列出状态字段允许的全部值；预算上限通过附加停止原因表达，不扩展状态枚举，
#: 以兼容旧消费者：仍有可用结果时为 completed，否则为 failed。
SUBAGENT_STATUS_VALUES: tuple[SubagentStatusValue, ...] = (
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "polling_timed_out",
)

#: 记录哪一种安全上限提前结束了运行；它是附加原因字段而非状态枚举值。
SubagentStopReasonValue = Literal["token_capped", "turn_capped", "loop_capped"]

SUBAGENT_STOP_REASON_VALUES: tuple[SubagentStopReasonValue, ...] = (
    "token_capped",
    "turn_capped",
    "loop_capped",
)

#: 将机器可读的停止原因映射为可合并到主代理结果文本中的简短说明。
_STOP_REASON_LABELS: dict[SubagentStopReasonValue, str] = {
    "token_capped": "token budget",
    "turn_capped": "turn budget",
    "loop_capped": "repeated tool-call loop",
}

#: 只有 completed 状态携带可恢复结果；达到上限但留下部分成果的运行也沿用该状态，
#: 其他终态只传递错误信息。
_RESULT_BEARING_STATUSES: frozenset[SubagentStatusValue] = frozenset({"completed"})

#: 将旧检查点中遗留的 max_turns_reached 状态映射到当前停止原因，避免历史任务在委派账本中
#: 永久停留为进行中；有部分结果时恢复为 completed，否则恢复为 failed。
_LEGACY_STATUS_NORMALIZATION: dict[str, SubagentStopReasonValue] = {
    "max_turns_reached": "turn_capped",
}


class StructuredSubagentResult(TypedDict):
    '''限定子代理结果在消息元数据中可传输的状态、摘要、摘要校验和错误字段。'''

    status: SubagentStatusValue
    stop_reason: NotRequired[SubagentStopReasonValue]
    result_brief: NotRequired[str]
    result_sha256: NotRequired[str]
    error: NotRequired[str]


def _bound_metadata_text(text: str, cap: int = SUBAGENT_METADATA_TEXT_MAX_CHARS) -> str:
    '''裁剪过长结果文本，同时保留开头和结尾以供主代理恢复关键信息。'''
    cleaned = text.strip()
    if len(cleaned) <= cap:
        return cleaned
    marker = "\n...\n"
    if cap <= len(marker):
        return cleaned[:cap]
    head = cap * 2 // 3
    tail = cap - head - len(marker)
    if tail <= 0:
        return cleaned[:cap]
    return f"{cleaned[:head]}{marker}{cleaned[-tail:]}"


def make_subagent_additional_kwargs(
    status: SubagentStatusValue,
    *,
    result: str | None = None,
    error: str | None = None,
    stop_reason: SubagentStopReasonValue | None = None,
    model_name: str | None = None,
    token_usage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    '''校验状态与停止原因，并生成长度受限、可跨消息传递的结构化结果字段。'''
    if status not in SUBAGENT_STATUS_VALUES:
        raise ValueError(f"invalid subagent status {status!r}; expected one of {SUBAGENT_STATUS_VALUES}")
    if stop_reason is not None and stop_reason not in SUBAGENT_STOP_REASON_VALUES:
        raise ValueError(f"invalid subagent stop_reason {stop_reason!r}; expected one of {SUBAGENT_STOP_REASON_VALUES}")
    payload: dict[str, object] = {SUBAGENT_STATUS_KEY: status}
    if status in _RESULT_BEARING_STATUSES and isinstance(result, str) and result.strip():
        payload[SUBAGENT_RESULT_BRIEF_KEY] = _bound_metadata_text(result)
        payload[SUBAGENT_RESULT_SHA256_KEY] = hashlib.sha256(result.encode("utf-8")).hexdigest()
    # 成功或保留部分成果的 completed 结果不携带错误字段，其他状态才记录错误。
    if status != "completed" and isinstance(error, str) and error.strip():
        payload[SUBAGENT_ERROR_KEY] = _bound_metadata_text(error)
    if stop_reason is not None:
        payload[SUBAGENT_STOP_REASON_KEY] = stop_reason
    if isinstance(model_name, str) and model_name.strip():
        payload[SUBAGENT_MODEL_NAME_KEY] = model_name.strip()
    normalized_usage = normalize_token_usage(token_usage)
    if normalized_usage is not None:
        payload[SUBAGENT_TOKEN_USAGE_KEY] = normalized_usage
    return payload


def normalize_token_usage(value: Any) -> dict[str, int] | None:
    '''验证令牌用量字段必须是非负整数，拒绝布尔值和不完整记录。'''
    if not isinstance(value, Mapping):
        return None
    normalized: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        amount = value.get(key)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            return None
        normalized[key] = amount
    return normalized


def format_subagent_result_message(
    status: SubagentStatusValue,
    *,
    result: str | None = None,
    error: str | None = None,
    stop_reason: SubagentStopReasonValue | None = None,
) -> tuple[str, str | None]:
    '''把状态、可用结果或错误格式化为主代理可读文本，并单独返回错误说明。'''
    result_text = "" if result is None else str(result)
    error_text = str(error).strip() if isinstance(error, str) else ""
    capped = _STOP_REASON_LABELS.get(stop_reason) if stop_reason is not None else None

    if status == "completed":
        if capped:
            return f"Task Succeeded (capped: {capped}). Result: {result_text}", None
        return f"Task Succeeded. Result: {result_text}", None

    if status == "cancelled":
        detail = error_text or "Task cancelled by user."
        if detail == "Task cancelled by user.":
            return detail, detail
        return f"Task cancelled by user. Error: {detail}", detail

    if status == "timed_out":
        detail = error_text or "Task timed out."
        if detail == "Task timed out.":
            return detail, detail
        return f"Task timed out. Error: {detail}", detail

    if status == "polling_timed_out":
        detail = error_text or "Task polling timed out."
        return detail, detail

    # 无可用结果的失败（包括轮数上限）会在消息中注明停止原因，便于主代理区分故障与限额。
    detail = error_text or "Task failed."
    if capped:
        if detail == "Task failed.":
            return f"Task failed (capped: {capped}).", detail
        return f"Task failed (capped: {capped}). Error: {detail}", detail
    if detail == "Task failed.":
        return detail, detail
    return f"Task failed. Error: {detail}", detail


def read_subagent_result_metadata(
    additional_kwargs: Mapping[str, object] | None,
) -> StructuredSubagentResult | None:
    '''从消息元数据读取并校验结构化结果，同时将旧版状态归一到当前契约。'''
    if not additional_kwargs:
        return None
    raw_status = additional_kwargs.get(SUBAGENT_STATUS_KEY)
    # 历史检查点仍可能包含已停止生成的旧状态；先归一化再校验，才能让委派账本进入终态。
    # 旧状态若包含可恢复摘要，则保留为 completed 并附加轮数上限原因，否则归为 failed。
    legacy_stop_reason = _LEGACY_STATUS_NORMALIZATION.get(raw_status) if isinstance(raw_status, str) else None
    if legacy_stop_reason is not None:
        raw_result_brief = additional_kwargs.get(SUBAGENT_RESULT_BRIEF_KEY)
        status = "completed" if (isinstance(raw_result_brief, str) and raw_result_brief.strip()) else "failed"
    elif raw_status in SUBAGENT_STATUS_VALUES:
        status = raw_status
    else:
        return None
    payload: StructuredSubagentResult = {"status": status}
    raw_result = additional_kwargs.get(SUBAGENT_RESULT_BRIEF_KEY)
    raw_hash = additional_kwargs.get(SUBAGENT_RESULT_SHA256_KEY)
    raw_error = additional_kwargs.get(SUBAGENT_ERROR_KEY)
    if status in _RESULT_BEARING_STATUSES and isinstance(raw_result, str) and raw_result.strip():
        payload["result_brief"] = _bound_metadata_text(raw_result)
        if isinstance(raw_hash, str) and _SHA256_HEX_RE.fullmatch(raw_hash):
            payload["result_sha256"] = raw_hash
    if status != "completed" and isinstance(raw_error, str) and raw_error.strip():
        payload["error"] = _bound_metadata_text(raw_error)
    # 消息中明确携带的停止原因优先于从旧状态推导出的兼容原因。
    raw_stop_reason = additional_kwargs.get(SUBAGENT_STOP_REASON_KEY)
    if isinstance(raw_stop_reason, str) and raw_stop_reason in SUBAGENT_STOP_REASON_VALUES:
        payload["stop_reason"] = raw_stop_reason
    elif legacy_stop_reason is not None:
        payload["stop_reason"] = legacy_stop_reason
    return payload
