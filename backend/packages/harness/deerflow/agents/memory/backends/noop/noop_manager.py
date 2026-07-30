'定义 noop_manager 模块提供的职责与可复用接口。\n\nNoop memory backend -- a functional empty :class:`MemoryManager`.\n\nProves the pluggable mechanism end-to-end (factory + drop-in discovery + config\nswitch) and doubles as the **template** for a new backend.\n\nPortability golden rule (see ``config.py`` for the full version): a backend\nreceives ALL host info through (1) the ABC method args and (2) the\n``backend_config`` dict. The ONLY ``from deerflow`` import allowed in this\nfolder is the ABC contract line below -- change that one line to port the\nbackend to another agent. Do NOT import deer-flow path helpers, config\nsingletons, or models; get everything from ``backend_config``.\n\nWriting a new backend:\n  1. Copy this folder to ``backends/<yourname>/``.\n  2. ``config.py``: declare your config knobs + ``from_backend_config`` (parse\n     ``backend_config``; read ``storage_path`` from it, NOT from deer-flow).\n  3. ``<yourname>_manager.py``: rename the class; ``__init__`` parses\n     ``backend_config`` into your config; implement the 9 ABC methods against\n     your memory system.\n  4. (Optional) implement the DeerMem-internal capability methods at the bottom\n     (``create_fact`` / ``delete_fact`` / ``update_fact`` / ``reload_memory`` /\n     ``warm``) so the host gateway\'s ``hasattr`` probes find them and the\n     fact-CRUD / reload / warm-up UI works.\n  5. ``__init__.py``: set ``MANAGER_CLASS = YourManager`` (relative import).\n  6. ``config.yaml``: ``manager_class: <yourname>``.\n\nReturn-shape note: the host gateway casts ``get_memory`` / ``export_memory`` /\n``clear_memory`` / ``import_memory`` returns to a DeerMem-shape response\n(``version`` / ``lastUpdated`` / ``user`` / ``history`` / ``facts[]``). A real\nbackend returns a dict castable to that shape (a non-DeerMem backend maps\nits native records into this shape). Noop returns the minimal ``{"facts": []}`` -- the\ngateway fills the rest with defaults.\n\nWith ``manager_class: noop`` the system runs with an empty memory: nothing is\nstored, nothing is injected, every read returns empty. Useful for tests, for\ndisabling memory without touching ``enabled``, and as a baseline.\n'

from __future__ import annotations

from typing import Any

# ABC contract -- the ONE allowed `from deerflow` in this backend folder.
# Change this single line (to the other agent's MemoryManager) to port.
from deerflow.agents.memory.manager import MemoryManager

from .config import NoopConfig


def _empty_memory() -> dict[str, Any]:
    '执行 _empty_memory 的明确职责，并返回与调用约定一致的结果。\n\nA fresh empty memory document (callers may mutate).\n\n    Minimal shape; the host gateway fills ``version`` / ``lastUpdated`` /\n    ``user`` / ``history`` with defaults. A real backend returns the full\n    DeerMem-shape doc (see the return-shape note in the module docstring).\n    '
    return {"facts": []}


class NoopMemoryManager(MemoryManager):
    '封装 NoopMemoryManager 的状态、协作关系与公开操作。\n\nBackend that stores and recalls nothing.\n\n    ``__init__`` parses ``backend_config`` into a :class:`NoopConfig` purely to\n    demonstrate the pattern -- noop ignores every field. A real backend reads\n    its knobs (storage root, model, ...) from ``self._config``.\n    '

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        super().__init__(backend_config)
        # Parse backend_config into a typed config. Noop ignores it; a real
        # backend uses self._config.* for storage root, model, etc. storage_path
        # comes from here (host-injected) -- never import a deer-flow path helper.
        self._config: NoopConfig = NoopConfig.from_backend_config(backend_config)

    # ── Write ────────────────────────────────────────────────────────────
    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        '执行 add 的明确职责，并返回与调用约定一致的结果'
        return None

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        '执行 add_nowait 的明确职责，并返回与调用约定一致的结果'
        return None

    # ── Read ─────────────────────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        '读取并返回，并遵守 get_context 所表达的接口约束'
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
        '执行 search 的明确职责，并返回与调用约定一致的结果'
        return []

    # ── Manage ───────────────────────────────────────────────────────────
    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '读取并返回，并遵守 get_memory 所表达的接口约束'
        return _empty_memory()

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        '删除目标资源并返回操作结果，并遵守 delete_memory 所表达的接口约束'
        return None

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '执行 clear_memory 的明确职责，并返回与调用约定一致的结果'
        return _empty_memory()

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '执行 import_memory 的明确职责，并返回与调用约定一致的结果'
        return _empty_memory()

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '执行 export_memory 的明确职责，并返回与调用约定一致的结果'
        return _empty_memory()

    # ── Lifecycle ───────────────────────────────────────────────────────
    def shutdown_flush(self, timeout: float) -> bool:
        '执行 shutdown_flush 的明确职责，并返回与调用约定一致的结果。\n\nNothing is ever queued, so shutdown drain is a clean no-op success.'
        return True

    # ── Optional DeerMem-internal capabilities (NOT on the ABC) ──────────
    # The host gateway discovers these via ``hasattr(manager, "<name>")`` and
    # returns 501 when absent. Implement the ones your backend supports so the
    # frontend's fact-CRUD / reload / warm-up works. Signatures must match what
    # the gateway calls. Uncomment & adapt for your backend:
    #
    # def delete_fact(self, fact_id, *, user_id=None, agent_name=None) -> dict:
    #     """Delete one memory by id (DELETE /memory/facts/{id})."""
    #     ...  # your_store.delete(fact_id)
    #     return self.get_memory(user_id=user_id, agent_name=agent_name)
    #
    # def create_fact(self, content: str, category: str = "context",
    #                 confidence: float = 0.5, *,
    #                 user_id: str | None = None,
    #                 agent_name: str | None = None,
    # ) -> tuple[dict, str | None]:
    #     """Manually add one memory (POST /memory/facts).
    #
    #     Returns ``(memory_data, fact_id)`` -- NOT a bare dict. ``content`` is
    #     positional (the memory_add tool passes it positionally); ``fact_id``
    #     is None when a storage cap (e.g. max_facts) evicted the just-added
    #     fact, so the caller reports "not stored" instead of a dangling id.
    #     Signatures must match what the gateway/client/tools call (see DeerMem).
    #     """
    #     ...  # your_store.add(content); fact_id = your_store.last_id()
    #     return self.get_memory(user_id=user_id, agent_name=agent_name), fact_id
    #
    # def update_fact(self, *, fact_id, content=None, category=None,
    #                 confidence=None, user_id=None, agent_name=None) -> dict:
    #     """Update one memory's text by id (PATCH /memory/facts/{id})."""
    #     ...  # your_store.update(fact_id, content)
    #     return self.get_memory(user_id=user_id, agent_name=agent_name)
    #
    # def reload_memory(self, *, user_id=None, agent_name=None) -> dict:
    #     """Drop caches & re-read storage (POST /memory/reload).
    #     If your backend has no cache, just delegate to get_memory(...)."""
    #     return self.get_memory(user_id=user_id, agent_name=agent_name)
    #
    # def warm(self) -> None:
    #     """Heavy one-time init at gateway startup (e.g. load a tokenizer).
    #     Probed via hasattr; absent = skipped. Keep it fast (host guards it
    #     with a timeout)."""
    #     ...
