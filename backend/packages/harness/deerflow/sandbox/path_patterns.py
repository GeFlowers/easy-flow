"""构建用于掩盖输出中路径的正则模式。"""

from __future__ import annotations

import re

# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
#
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
#
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
_SEGMENT_BOUNDARY = r"(?=/|$|[^\w./-])"

# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
_PATH_TAIL = r"(?:[/\\][^\s\"';&|<>()]*)?"


def build_output_mask_pattern(base: str, *, separator_agnostic: bool = False) -> re.Pattern[str]:
    """为指定根路径构建可匹配其后续路径片段的输出掩盖模式。"""
    escaped = re.escape(base)
    if separator_agnostic:
        escaped = escaped.replace(r"\\", r"[/\\]")
    return re.compile(escaped + _SEGMENT_BOUNDARY + _PATH_TAIL)
