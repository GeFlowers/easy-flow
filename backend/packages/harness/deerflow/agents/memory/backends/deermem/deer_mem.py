'定义 deer_mem 模块提供的职责与可复用接口。\n\nDeerMem -- the default :class:`MemoryManager` backend (self-contained).\n\nDeerMem wraps the DeerFlow memory machinery (the five ``core/`` modules:\nstorage / queue / updater / prompt / message_processing) behind the\nbackend-neutral :class:`~deerflow.agents.memory.manager.MemoryManager`\ncontract. DeerMem owns its storage / queue / updater as injected instance\nattributes (no module-level singletons): the factory passes ``backend_config``\nto ``__init__``, which parses it into a :class:`DeerMemConfig` and constructs\nthe dependencies. Behaviour matches the pre-abstraction code: the same filter +\nhuman/ai validation + correction/reinforcement detection feeds the same\ndebounced queue; the same ``format_memory_for_injection`` produces injection\ntext; the same CRUD backs the management endpoints.\n\nDeerMem-private concerns (filter/detect, the ``<memory>`` wrap, ``enabled``\ngating, the facts model) deliberately stay OUT of the ABC -- they live here.\nMethods not on the ABC (``warm`` / ``reload_memory`` / ``create_fact`` /\n``delete_fact`` / ``update_fact``) are DeerMem internals exposed for\n``hasattr`` capability probing: the gateway probes ``hasattr(manager, "warm")``\nat startup and the gateway/client probe ``hasattr(manager, "create_fact")`` for\nfact CRUD, rather than importing DeerMem, so a non-DeerMem (or removed) backend\nnever breaks those modules at import time (see MemoryManager plan, step 8).\n'

from __future__ import annotations

import logging
from typing import Any

from deerflow.agents.memory.manager import MemoryManager

from .deermem.config import DeerMemConfig
from .deermem.core.llm import build_llm
from .deermem.core.message_processing import (
    detect_correction,
    detect_reinforcement,
    filter_messages_for_memory,
)
from .deermem.core.prompt import format_memory_for_injection, warm_tiktoken_cache
from .deermem.core.queue import MemoryUpdateQueue
from .deermem.core.storage import create_storage
from .deermem.core.updater import MemoryUpdater, _coerce_source_confidence

logger = logging.getLogger(__name__)


class DeerMem(MemoryManager):
    '封装 DeerMem 的状态、协作关系与公开操作。\n\nDefault memory backend: file-backed facts + debounced LLM extraction.'

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致。\n\nConstruct DeerMem with its dependencies (dependency injection).\n\n        Args:\n            backend_config: DeerMem-private config dict (from\n                ``MemoryConfig.backend_config``). Parsed into a\n                :class:`DeerMemConfig` (defaults apply when empty/None).\n        '
        self._config = DeerMemConfig.from_backend_config(backend_config)
        self._storage = create_storage(self._config)
        # host_llm (host-injected default model) takes precedence over build_llm(model)
        # so zero-config DeerMem (empty `model`) still extracts via the app default,
        # mirroring pre-abstraction `model_name: null`. Standalone (no factory) -> None.
        self._llm = self._config.host_llm if self._config.host_llm is not None else build_llm(self._config.model)
        self._updater = MemoryUpdater(self._config, self._storage, self._llm)
        self._queue = MemoryUpdateQueue(self._config, self._updater)

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
        '执行 add 的明确职责，并返回与调用约定一致的结果。\n\nFilter, validate, detect signals, then enqueue (debounced).\n\n        Mirrors the preprocessing that lived in ``MemoryMiddleware.after_agent``\n        before the abstraction. The ``enabled`` gate and\n        ``thread_id``/``user_id``/``trace_id`` resolution stay at the call site.\n        '
        prepared = self._prepare_update(messages)
        if prepared is None:
            return
        filtered, correction_detected, reinforcement_detected = prepared
        self._queue.add(
            thread_id=thread_id,
            messages=filtered,
            agent_name=agent_name,
            user_id=user_id,
            trace_id=trace_id,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        '执行 add_nowait 的明确职责，并返回与调用约定一致的结果。\n\nFilter, validate, detect signals, then enqueue for immediate flush.\n\n        Mirrors the preprocessing that lived in ``memory_flush_hook`` before\n        the abstraction. Used right before summarization removes messages.\n        '
        prepared = self._prepare_update(messages)
        if prepared is None:
            return
        filtered, correction_detected, reinforcement_detected = prepared
        self._queue.add_nowait(
            thread_id=thread_id,
            messages=filtered,
            agent_name=agent_name,
            user_id=user_id,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )

    def _prepare_update(
        self,
        messages: list[Any],
    ) -> tuple[list[Any], bool, bool] | None:
        '执行 _prepare_update 的明确职责，并返回与调用约定一致的结果。\n\nFilter to user+final-AI messages, require both, detect signals.\n\n        Returns ``(filtered, correction_detected, reinforcement_detected)``\n        or ``None`` when there is no meaningful conversation (missing a user\n        or an assistant turn). Identical logic to the pre-abstraction\n        middleware/hook so behaviour is unchanged.\n        '
        filtered = filter_messages_for_memory(
            messages,
            should_keep_hidden_message=self._config.should_keep_hidden_message,
        )
        user_messages = [m for m in filtered if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered if getattr(m, "type", None) == "ai"]
        if not user_messages or not assistant_messages:
            return None
        correction_detected = detect_correction(filtered)
        reinforcement_detected = not correction_detected and detect_reinforcement(filtered)
        return filtered, correction_detected, reinforcement_detected

    # ── Read ─────────────────────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        "读取并返回，并遵守 get_context 所表达的接口约束。\n\nLoad memory and format it for injection (plain text, no wrap).\n\n        Format parameters come from DeerMem's own ``DeerMemConfig`` (set at\n        construction from ``backend_config``). The ``enabled``/\n        ``injection_enabled`` gate and the ``<memory>`` wrapping stay at the\n        call site (``_get_memory_context``); this returns only the body.\n        "
        memory_data = self._updater.get_memory_data(agent_name=agent_name, user_id=user_id)
        return format_memory_for_injection(
            memory_data,
            max_tokens=self._config.max_injection_tokens,
            use_tiktoken=(self._config.token_counting == "tiktoken"),
            guaranteed_categories=self._config.guaranteed_categories,
            guaranteed_token_budget=self._config.guaranteed_token_budget,
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        '执行 search 的明确职责，并返回与调用约定一致的结果。\n\nCase-insensitive substring search over stored facts.\n\n        Stand-in for the planned BM25+vector+MMR retrieval\n        (``core/retrieval.py``): returns facts whose ``content`` contains the\n        query, ranked by confidence desc, capped at ``top_k``. ``category``\n        filters BEFORE the ``top_k`` slice so a category-scoped search is not\n        starved by higher-confidence facts in other categories. Sufficient for\n        the tool-driven memory mode; upgrade to semantic retrieval later\n        without changing call sites.\n        '
        if not query or not query.strip() or top_k <= 0:
            return []
        query_lower = query.strip().lower()
        memory_data = self._updater.get_memory_data(agent_name=agent_name, user_id=user_id)
        matched = [fact for fact in memory_data.get("facts", []) if isinstance(fact.get("content"), str) and query_lower in fact["content"].lower() and (category is None or fact.get("category") == category)]
        matched.sort(key=_coerce_source_confidence, reverse=True)
        return matched[:top_k]

    # ── Manage ───────────────────────────────────────────────────────────
    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '读取并返回，并遵守 get_memory 所表达的接口约束'
        return self._updater.get_memory_data(agent_name=agent_name, user_id=user_id)

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        '删除目标资源并返回操作结果，并遵守 delete_memory 所表达的接口约束。\n\nNot implemented this phase (storage/updater deletion is a future ``core/`` addition).'
        raise NotImplementedError("DeerMem.delete_memory is not implemented yet")

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '执行 clear_memory 的明确职责，并返回与调用约定一致的结果'
        return self._updater.clear_memory_data(agent_name=agent_name, user_id=user_id)

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '执行 import_memory 的明确职责，并返回与调用约定一致的结果'
        return self._updater.import_memory_data(memory_data, agent_name=agent_name, user_id=user_id)

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '执行 export_memory 的明确职责，并返回与调用约定一致的结果。\n\nNot implemented this phase (no distinct export yet; /export routes via get_memory).'
        raise NotImplementedError("DeerMem.export_memory is not implemented yet")

    # ── Lifecycle ───────────────────────────────────────────────────────
    def shutdown_flush(self, timeout: float) -> bool:
        "执行 shutdown_flush 的明确职责，并返回与调用约定一致的结果。\n\nDrain the debounce queue within ``timeout`` on graceful shutdown.\n\n        Delegates to the queue's bounded synchronous flush, which joins an\n        in-flight worker first (so contexts a debounce Timer already pulled out\n        of the queue are not lost on exit) and otherwise drains the queue on a\n        daemon thread with a real hard timeout (the memory-update LLM call is\n        synchronous and cannot be interrupted). Returns ``True`` only when the\n        drain genuinely finished within ``timeout``.\n        "
        return self._queue.flush_sync(timeout)

    # ── DeerMem-internal (NOT on the ABC; reached via hasattr probing) ───
    def warm(self) -> bool:
        '执行 warm 的明确职责，并返回与调用约定一致的结果。\n\nPre-warm DeerMem-specific resources (the tiktoken encoding cache).\n\n        Backend-agnostic startup code probes ``hasattr(manager, "warm")`` and\n        calls this off the event loop. Non-DeerMem backends lack the attribute,\n        so their warm-up is skipped entirely (e.g. mem0 does not use tiktoken).\n        Returns True if the encoding loaded (or was already cached, or warming\n        was unnecessary); False if tiktoken is unavailable or the download\n        failed.\n        '
        if self._config.token_counting == "char":
            logger.info("token_counting='char'; tiktoken not used, skipping warm-up")
            return True
        return warm_tiktoken_cache()

    def reload_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '执行 reload_memory 的明确职责，并返回与调用约定一致的结果。\n\nDrop the cached memory document and reload from disk.'
        return self._updater.reload_memory_data(agent_name=agent_name, user_id=user_id)

    def create_fact(
        self,
        content: str,
        category: str = "context",
        confidence: float = 0.5,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        '创建并返回，并遵守 create_fact 所表达的接口约束'
        return self._updater.create_memory_fact(
            content,
            category=category,
            confidence=confidence,
            agent_name=agent_name,
            user_id=user_id,
        )

    def delete_fact(
        self,
        fact_id: str,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        '删除目标资源并返回操作结果，并遵守 delete_fact 所表达的接口约束'
        return self._updater.delete_memory_fact(fact_id, agent_name=agent_name, user_id=user_id)

    def update_fact(
        self,
        fact_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        '更新目标状态并返回最新结果，并遵守 update_fact 所表达的接口约束'
        return self._updater.update_memory_fact(
            fact_id,
            content=content,
            category=category,
            confidence=confidence,
            agent_name=agent_name,
            user_id=user_id,
        )
