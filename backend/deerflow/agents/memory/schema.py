'''校验并规范化用户画像与历史背景的单段摘要格式。'''

from collections.abc import Mapping
from typing import Any


MEMORY_SCHEMA_VERSION = "2.0"
def normalize_summary(value: Any) -> dict[str, str]:
    """校验并规范化当前的单段摘要。"""
    if not isinstance(value, Mapping):
        raise ValueError("记忆摘要必须是对象")
    if value and ("summary" not in value or "updatedAt" not in value):
        raise ValueError("记忆摘要必须包含 summary 和 updatedAt")
    summary = value.get("summary", "")
    updated_at = value.get("updatedAt", "")
    if not isinstance(summary, str) or not isinstance(updated_at, str):
        raise ValueError("记忆摘要及更新时间必须是文本")
    return {"summary": summary.strip(), "updatedAt": updated_at}


def normalize_memory(memory: Mapping[str, Any]) -> dict[str, Any]:
    '''生成单段摘要版本的记忆副本，保持事实及其他顶层信息不变。'''
    if not isinstance(memory, Mapping):
        raise ValueError("记忆文档必须是对象")
    return {
        **memory,
        "version": MEMORY_SCHEMA_VERSION,
        "user": normalize_summary(memory.get("user", {})),
        "history": normalize_summary(memory.get("history", {})),
    }
