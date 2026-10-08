'''

DeerFlow 运行时的存储器提供模块。

重新导出异步提供方（供常驻服务使用）和同步提供方
（供命令行工具及嵌入式客户端使用）的公开接口。

异步用法（FastAPI 生命周期管理）::

    from deerflow.runtime.store import make_store

    async with make_store() as store:
        app.state.store = store

同步用法（命令行／DeerFlowClient）::

    from deerflow.runtime.store import get_store, store_context

    store = get_store()                   # 单例
    with store_context() as store: ...    # 单次上下文
'''

from .async_provider import make_store
from .provider import get_store, reset_store, store_context

__all__ = [
    "make_store",
    "get_store",
    "reset_store",
    "store_context",
]
