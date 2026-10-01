'''为长期存活的智能体中间件提供有界状态容器。

A small bounded ``OrderedDict`` shared by guard middlewares.

Guard middlewares (``TokenBudgetMiddleware``, ``LoopDetectionMiddleware``) keep
per-``run_id`` state that must not grow without bound on abandoned or reused
runs. This module provides the single shared implementation so both middlewares
cap identically and a future guard does not reinvent it.
'''

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class BoundedDict(OrderedDict):
    '''容量达到上限时按插入顺序淘汰最早的键值项。

    An ``OrderedDict`` that evicts the oldest entry once ``maxsize`` is reached.

        Used for per-``run_id`` state (stop-reason flags, pending warnings, usage
        accumulators) so a long-lived middleware instance on the lead agent cannot
        leak memory across many runs. Insertion order is preserved, so the
        least-recently-inserted key is evicted first.
    '''

    def __init__(self, maxsize: int = 1000, *args: Any, **kwds: Any) -> None:
        '''使用给定容量和初始字典内容初始化有界字典。'''
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __setitem__(self, key: Any, value: Any) -> None:
        '''写入键值；新键写满容量时先移除最早插入的条目。'''
        if key not in self:
            if len(self) >= self.maxsize:
                self.popitem(last=False)
        super().__setitem__(key, value)
