'''提供代理状态类型的延迟导出入口。'''

__all__ = [
    "SandboxState",
    "ThreadState",
]


def __getattr__(name: str):
    '''按需导入公开符号，避免包导入时初始化完整代理依赖图。'''
    if name in {"SandboxState", "ThreadState"}:
        from .thread_state import SandboxState, ThreadState

        exports = {"SandboxState": SandboxState, "ThreadState": ThreadState}
        globals().update(exports)
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
