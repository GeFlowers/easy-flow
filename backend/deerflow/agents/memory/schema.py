'''统一用户画像与历史背景的单段摘要格式，并兼容旧的六分区备份。'''

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


MEMORY_SCHEMA_VERSION = "2.0"
LEGACY_SUMMARY_KEYS = {
    "user": ("workContext", "personalContext", "topOfMind"),
    "history": ("recentMonths", "earlierContext", "longTermBackground"),
}


def normalize_summary(value: Any, *, section: str) -> dict[str, str]:
    '''合并旧分区的非空摘要并去重，保留最新更新时间；新格式直接规范化。'''
    if not isinstance(value, Mapping):
        raise ValueError("记忆摘要必须是对象")
    summaries: list[str] = []
    dates: list[tuple[datetime, str]] = []
    entries = [value, *(value[key] for key in LEGACY_SUMMARY_KEYS[section] if key in value)]
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("记忆摘要分区必须是对象")
        text = entry.get("summary", "")
        updated = entry.get("updatedAt", "")
        if not isinstance(text, str) or not isinstance(updated, str):
            raise ValueError("记忆摘要及更新时间必须是文本")
        text = text.strip()
        if text and text not in summaries:
            summaries.append(text)
        if updated:
            try:
                parsed = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                dates.append((parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed, updated))
            except ValueError:
                pass
    fallback = value.get("updatedAt", "")
    return {
        "summary": "\n\n".join(summaries),
        "updatedAt": max(dates, key=lambda item: item[0])[1] if dates else fallback,
    }


def normalize_memory(memory: Mapping[str, Any]) -> dict[str, Any]:
    '''生成单段摘要版本的记忆副本，保持事实及其他顶层信息不变。'''
    if not isinstance(memory, Mapping):
        raise ValueError("记忆文档必须是对象")
    return {
        **memory,
        "version": MEMORY_SCHEMA_VERSION,
        "user": normalize_summary(memory.get("user", {}), section="user"),
        "history": normalize_summary(memory.get("history", {}), section="history"),
    }
