"定义 config 模块提供的职责与可复用接口。\n\nNoop backend config -- TEMPLATE for parsing ``backend_config``.\n\nReference for how a new memory backend configures itself. **Portability golden\nrule** (read before writing a backend):\n\n    A backend receives ALL host-provided info through exactly TWO channels:\n      1. The :class:`MemoryManager` ABC method arguments (``manager.py``) --\n         ``user_id`` / ``agent_name`` / ``thread_id`` / ``messages`` / etc.\n      2. The ``backend_config`` dict (passed to ``__init__``).\n    It MUST NOT import deer-flow modules or hardcode deer-flow paths. The ONLY\n    ``from deerflow`` line allowed in the whole backend folder is the ABC\n    contract import in ``<name>_manager.py``::\n\n        from deerflow.agents.memory.manager import MemoryManager\n\n    That single line ties the backend to the host; change it (and only it) to\n    port the backend to another agent. Everything else -- storage root, model,\n    hooks -- arrives via ``backend_config``.\n\nWhat the factory (``manager.py::get_memory_manager``) injects into\n``backend_config`` for every backend:\n  - ``storage_path`` (str): a writable state dir (the host's default, or\n    whatever the user sets in config.yaml). **Use this as your storage root** --\n    do NOT call a deer-flow path helper yourself.\n  - ``tracing_callback`` (Callable | None): host default for tracing the\n    backend's LLM calls (langfuse). Declare a slot + consume it if your backend\n    traces; otherwise ignore (unknown-key filtering drops it).\n  - ``should_keep_hidden_message`` (Callable | None): host default for keeping\n    ``hide_from_ui`` messages (human-clarification). Consume if your backend\n    filters hidden messages; otherwise ignore.\n  - Plus the user's ``config.yaml::memory.backend_config`` keys (your backend's\n    own knobs: ``model``, ``vector_store``, ``embedder``, thresholds, etc.).\n\n``NoopConfig`` below mirrors that surface. Noop stores nothing, so it ignores\nevery field -- but copy this structure, rename, and fill in your own knobs.\n"

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class NoopConfig:
    '封装 NoopConfig 的状态、协作关系与公开操作。\n\nParsed config for the noop backend (template -- noop ignores all fields).\n\n    A real backend declares its own knobs here (e.g. ``model``, ``vector_store``,\n    ``max_facts``) and parses them in :meth:`from_backend_config`.\n    '

    #: Writable state dir, host-injected. A real backend lands its storage
    #: (DB / vector store / JSON) under here. Noop ignores it.
    storage_path: str = ""

    #: Example backend-private knob (would come from config.yaml
    #: ``memory.backend_config.example_option``). Replace with your own.
    example_option: str = "default"

    #: Host-injected hook (optional). A backend that traces its LLM calls calls
    #: ``self._config.tracing_callback(invoke_config, *, thread_id, user_id,
    #: trace_id, model_name)`` before invoking. ``None`` = no tracing.
    tracing_callback: Callable[..., Any] | None = None

    #: Host-injected hook (optional). A backend that filters ``hide_from_ui``
    #: messages calls ``self._config.should_keep_hidden_message(additional_kwargs)``
    #: -> bool (True = keep despite hide_from_ui). ``None`` = skip all hidden.
    should_keep_hidden_message: Callable[[Any], bool] | None = None

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> NoopConfig:
        "执行 from_backend_config 的明确职责，并返回与调用约定一致的结果。\n\nBuild a config from the ``backend_config`` dict.\n\n        Usage in your manager's ``__init__``::\n\n            super().__init__(backend_config)\n            self._config = YourConfig.from_backend_config(backend_config)\n\n        Reads ONLY known keys; unknown keys (including host-injected slots this\n        backend doesn't consume) are ignored -- so the host can safely inject\n        shared slots like ``tracing_callback`` for every backend without\n        breaking ones that don't use them.\n        "
        cfg = dict(backend_config or {})
        return cls(
            storage_path=str(cfg.get("storage_path") or ""),
            example_option=str(cfg.get("example_option", "default")),
            tracing_callback=cfg.get("tracing_callback"),
            should_keep_hidden_message=cfg.get("should_keep_hidden_message"),
        )
