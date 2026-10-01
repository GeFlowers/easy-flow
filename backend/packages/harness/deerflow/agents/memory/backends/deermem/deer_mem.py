'''将 DeerMem 内部的存储、队列和事实更新流程适配到统一记忆管理器接口。

DeerMem -- the default :class:`MemoryManager` backend (self-contained).

DeerMem wraps the DeerFlow memory machinery (the five ``core/`` modules:
storage / queue / updater / prompt / message_processing) behind the
backend-neutral :class:`~deerflow.agents.memory.manager.MemoryManager`
contract. DeerMem owns its storage / queue / updater as injected instance
attributes (no module-level singletons): the factory passes ``backend_config``
to ``__init__``, which parses it into a :class:`DeerMemConfig` and constructs
the dependencies. Behaviour matches the pre-abstraction code: the same filter +
human/ai validation + correction/reinforcement detection feeds the same
debounced queue; the same ``format_memory_for_injection`` produces injection
text; the same CRUD backs the management endpoints.

DeerMem-private concerns (filter/detect, the ``<memory>`` wrap, ``enabled``
gating, the facts model) deliberately stay OUT of the ABC -- they live here.
Methods not on the ABC (``warm`` / ``reload_memory`` / ``create_fact`` /
``delete_fact`` / ``update_fact``) are DeerMem internals exposed for
``hasattr`` capability probing: the gateway probes ``hasattr(manager, "warm")``
at startup and the gateway/client probe ``hasattr(manager, "create_fact")`` for
fact CRUD, rather than importing DeerMem, so a non-DeerMem (or removed) backend
never breaks those modules at import time (see MemoryManager plan, step 8).
'''

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
    '''负责将对话整理为记忆事实、异步排队更新，并向智能体提供记忆读写能力。'''

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        '''解析后端配置并创建存储、模型、事实更新器和延迟更新队列。'''
        self._config = DeerMemConfig.from_backend_config(backend_config)
        self._storage = create_storage(self._config)
        self._llm = self._config.host_llm if self._config.host_llm is not None else build_llm(self._config.model)
        self._updater = MemoryUpdater(self._config, self._storage, self._llm)
        self._queue = MemoryUpdateQueue(self._config, self._updater)

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        '''筛选有效对话并识别纠正或强化信号，再将记忆更新加入防抖队列。'''
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
        '''整理当前对话并请求立即刷新队列，供消息摘要裁剪前保存记忆使用。'''
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
        '''筛出有效的用户和助手对话；缺少任一方时跳过，否则检测纠正与强化信号。'''
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

    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        '''读取用户记忆并按配置裁剪、格式化为可注入提示的纯文本内容。'''
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
        '''在用户事实中执行不区分大小写的内容包含搜索，可按类别筛选并按置信度排序。'''
        if not query or not query.strip() or top_k <= 0:
            return []
        query_lower = query.strip().lower()
        memory_data = self._updater.get_memory_data(agent_name=agent_name, user_id=user_id)
        matched = [fact for fact in memory_data.get("facts", []) if isinstance(fact.get("content"), str) and query_lower in fact["content"].lower() and (category is None or fact.get("category") == category)]
        matched.sort(key=_coerce_source_confidence, reverse=True)
        return matched[:top_k]

    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''返回指定用户和代理的完整记忆数据。'''
        return self._updater.get_memory_data(agent_name=agent_name, user_id=user_id)

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        '''整份记忆删除尚未实现；当前存储层没有对应的删除操作。'''
        raise NotImplementedError("DeerMem.delete_memory is not implemented yet")

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''清除指定用户和代理的全部记忆数据。'''
        return self._updater.clear_memory_data(agent_name=agent_name, user_id=user_id)

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''将提供的记忆数据导入指定用户和代理的存储。'''
        return self._updater.import_memory_data(memory_data, agent_name=agent_name, user_id=user_id)

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''独立导出流程尚未实现；当前接口由调用方读取记忆数据完成导出。'''
        raise NotImplementedError("DeerMem.export_memory is not implemented yet")

    def shutdown_flush(self, timeout: float) -> bool:
        '''在给定时限内同步刷新待处理记忆，供服务优雅关闭时尽量避免丢失更新。'''
        return self._queue.flush_sync(timeout)

    def warm(self) -> bool:
        '''若使用基于编码器的令牌计数，则提前加载其缓存；字符计数模式无需预热。'''
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
        '''丢弃指定用户记忆的内存缓存并从持久化存储重新载入。'''
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
        '''创建一条记忆事实，并返回新事实及可能的校验错误。'''
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
        '''按事实编号删除指定用户记忆中的一条事实。'''
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
        '''按事实编号更新内容、类别或置信度，并返回更新后的记忆结果。'''
        return self._updater.update_memory_fact(
            fact_id,
            content=content,
            category=category,
            confidence=confidence,
            agent_name=agent_name,
            user_id=user_id,
        )
