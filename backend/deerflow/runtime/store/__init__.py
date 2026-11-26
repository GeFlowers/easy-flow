'''

DeerFlow 运行时的存储器提供模块。

异步用法（FastAPI 生命周期管理）::

    from deerflow.runtime.store import make_store

    async with make_store() as store:
        app.state.store = store

'''

from .async_provider import make_store

__all__ = [
    "make_store",
]
