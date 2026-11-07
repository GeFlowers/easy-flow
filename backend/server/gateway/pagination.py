'''供网关路由复用的分页边界处理工具。'''

from __future__ import annotations


def trim_run_message_page(rows: list[dict], *, limit: int, after_seq: int | None) -> tuple[list[dict], bool]:
    '''裁剪以 ``limit + 1`` 查询的运行消息页，并保留正确的翻页边界。'''
    has_more = len(rows) > limit
    if not has_more:
        return rows, False

    if after_seq is not None:
        return rows[:limit], True

    return rows[-limit:], True
