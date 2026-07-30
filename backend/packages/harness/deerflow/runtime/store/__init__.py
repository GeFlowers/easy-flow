'定义 __init__ 模块提供的职责与可复用接口。\n\nStore provider for the DeerFlow runtime.\n\nRe-exports the public API of both the async provider (for long-running\nservers) and the sync provider (for CLI tools and the embedded client).\n\nAsync usage (FastAPI lifespan)::\n\n    from deerflow.runtime.store import make_store\n\n    async with make_store() as store:\n        app.state.store = store\n\nSync usage (CLI / DeerFlowClient)::\n\n    from deerflow.runtime.store import get_store, store_context\n\n    store = get_store()                   # singleton\n    with store_context() as store: ...    # one-shot\n'

from .async_provider import make_store
from .provider import get_store, reset_store, store_context

__all__ = [
    # async
    "make_store",
    # sync
    "get_store",
    "reset_store",
    "store_context",
]
