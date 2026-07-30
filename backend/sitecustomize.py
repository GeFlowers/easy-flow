'定义 sitecustomize 模块提供的职责与可复用接口。\n\nProcess-wide Python startup customizations for backend entrypoints.\n\nWhen ``backend/`` is on ``sys.path``, Python imports this module during\ninterpreter startup. Keep changes here suitable for all gateway, script,\nmigration, and test entrypoints that run in that environment.\n'

from __future__ import annotations

import asyncio
import sys


def _configure_windows_event_loop_policy() -> None:
    '执行 _configure_windows_event_loop_policy 的明确职责，并返回与调用约定一致的结果'
    if sys.platform != "win32":
        return

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:
        return

    if not isinstance(asyncio.get_event_loop_policy(), selector_policy):
        asyncio.set_event_loop_policy(selector_policy())


_configure_windows_event_loop_policy()
