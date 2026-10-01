'''实现不保存任何对话内容的记忆管理器，用于关闭记忆或作为后端扩展范例。

Noop memory backend -- a functional empty :class:`MemoryManager`.

Proves the pluggable mechanism end-to-end (factory + drop-in discovery + config
switch) and doubles as the **template** for a new backend.

Portability golden rule (see ``config.py`` for the full version): a backend
receives ALL host info through (1) the ABC method args and (2) the
``backend_config`` dict. The ONLY ``from deerflow`` import allowed in this
folder is the ABC contract line below -- change that one line to port the
backend to another agent. Do NOT import deer-flow path helpers, config
singletons, or models; get everything from ``backend_config``.

Writing a new backend:
  1. Copy this folder to ``backends/<yourname>/``.
  2. ``config.py``: declare your config knobs + ``from_backend_config`` (parse
     ``backend_config``; read ``storage_path`` from it, NOT from deer-flow).
  3. ``<yourname>_manager.py``: rename the class; ``__init__`` parses
     ``backend_config`` into your config; implement the 9 ABC methods against
     your memory system.
  4. (Optional) implement the DeerMem-internal capability methods at the bottom
     (``create_fact`` / ``delete_fact`` / ``update_fact`` / ``reload_memory`` /
     ``warm``) so the host gateway's ``hasattr`` probes find them and the
     fact-CRUD / reload / warm-up UI works.
  5. ``__init__.py``: set ``MANAGER_CLASS = YourManager`` (relative import).
  6. ``config.yaml``: ``manager_class: <yourname>``.

Return-shape note: the host gateway casts ``get_memory`` / ``export_memory`` /
``clear_memory`` / ``import_memory`` returns to a DeerMem-shape response
(``version`` / ``lastUpdated`` / ``user`` / ``history`` / ``facts[]``). A real
backend returns a dict castable to that shape (a non-DeerMem backend maps
its native records into this shape). Noop returns the minimal ``{"facts": []}`` -- the
gateway fills the rest with defaults.

With ``manager_class: noop`` the system runs with an empty memory: nothing is
stored, nothing is injected, every read returns empty. Useful for tests, for
disabling memory without touching ``enabled``, and as a baseline.
'''

from __future__ import annotations

from typing import Any

from deerflow.agents.memory.manager import MemoryManager

from .config import NoopConfig


def _empty_memory() -> dict[str, Any]:
    '''创建最小空记忆文档，供读取、清空和导出操作返回。'''
    return {"facts": []}


class NoopMemoryManager(MemoryManager):
    '''实现记忆管理器协议但不存储、不召回任何对话或事实。'''

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        '''解析宿主传入的后端配置，供示例说明配置注入方式；此后端不会使用这些配置。'''
        super().__init__(backend_config)
        self._config: NoopConfig = NoopConfig.from_backend_config(backend_config)

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        '''忽略排队记忆更新的请求，不保存本轮对话。'''
        return None

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        '''忽略无需等待的记忆更新请求。'''
        return None

    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        '''不注入任何记忆上下文，始终返回空文本。'''
        return ""

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        '''不执行记忆检索，始终返回空结果列表。'''
        return []

    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''返回符合最小记忆响应结构的空文档。'''
        return _empty_memory()

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        '''保持空操作；此管理器没有持久化记忆可删除。'''
        return None

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''返回空记忆文档，表示清空后的状态。'''
        return _empty_memory()

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''忽略导入内容并返回空记忆状态，不写入任何数据。'''
        return _empty_memory()

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''导出最小空记忆文档。'''
        return _empty_memory()

    def shutdown_flush(self, timeout: float) -> bool:
        '''空后端不会排队写入任务，因此关闭刷新无需操作并始终报告成功。'''
        return True
