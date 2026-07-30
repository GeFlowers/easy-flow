'定义 _bounded_dict 模块提供的职责与可复用接口。\n\nA small bounded ``OrderedDict`` shared by guard middlewares.\n\nGuard middlewares (``TokenBudgetMiddleware``, ``LoopDetectionMiddleware``) keep\nper-``run_id`` state that must not grow without bound on abandoned or reused\nruns. This module provides the single shared implementation so both middlewares\ncap identically and a future guard does not reinvent it.\n'

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class BoundedDict(OrderedDict):
    '封装 BoundedDict 的状态、协作关系与公开操作。\n\nAn ``OrderedDict`` that evicts the oldest entry once ``maxsize`` is reached.\n\n    Used for per-``run_id`` state (stop-reason flags, pending warnings, usage\n    accumulators) so a long-lived middleware instance on the lead agent cannot\n    leak memory across many runs. Insertion order is preserved, so the\n    least-recently-inserted key is evicted first.\n    '

    def __init__(self, maxsize: int = 1000, *args: Any, **kwds: Any) -> None:
        """使用给定容量和初始字典内容初始化有界字典。"""
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __setitem__(self, key: Any, value: Any) -> None:
        """写入键值；新键写满容量时先移除最早插入的条目。"""
        if key not in self:
            if len(self) >= self.maxsize:
                self.popitem(last=False)
        super().__setitem__(key, value)
