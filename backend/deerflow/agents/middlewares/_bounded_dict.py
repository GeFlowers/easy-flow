'''为长期存活的智能体中间件提供有界状态容器。

保护性中间件共用的轻量有界 ``OrderedDict``。

``TokenBudgetMiddleware`` 和 ``LoopDetectionMiddleware`` 按 ``run_id`` 保存状态；
运行被放弃或重复使用时，这些状态不能无限增长。本模块提供共用实现，
使两者采用一致的容量限制，并供后续保护性中间件复用。
'''

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class BoundedDict(OrderedDict):
    '''容量达到上限时按插入顺序淘汰最早的键值项。

    达到 ``maxsize`` 后淘汰最早条目的 ``OrderedDict``。

        用于按 ``run_id`` 保存终止原因标记、待发送警告和用量累加器，
        防止主代理上长期存活的中间件实例随运行次数增多而泄漏内存。
        保留插入顺序，因此最早插入的键最先被淘汰。
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
