'''为后端 Python 进程设置启动时需要的全局兼容选项。

当 ``backend/`` 位于 Python 模块搜索路径中时，Python 启动阶段会自动导入此文件。
目前它只在 Windows 上切换异步事件循环策略；Linux 和 macOS 不受影响。
'''

from __future__ import annotations

import asyncio
import sys


def _configure_windows_event_loop_policy() -> None:
    '''在 Windows 上启用选择器事件循环策略，以兼容依赖该策略的异步功能。'''
    if sys.platform != "win32":
        return

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:
        return

    if not isinstance(asyncio.get_event_loop_policy(), selector_policy):
        asyncio.set_event_loop_policy(selector_policy())


_configure_windows_event_loop_policy()
