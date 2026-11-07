'''显式创建数据库驱动兼容的事件循环，不修改进程全局循环策略。'''

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar('T')


def create_event_loop() -> asyncio.AbstractEventLoop:
    '''Windows 使用选择器循环，其他平台遵循当前已配置的循环策略。'''
    if sys.platform == 'win32':
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


def run_async(coroutine: Coroutine[Any, Any, T]) -> T:
    '''在显式选择的临时循环中运行协程，并由标准运行器完成资源清理。'''
    return asyncio.run(coroutine, loop_factory=create_event_loop)
