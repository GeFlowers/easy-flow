'''将 DeerMem 内部的存储、队列和事实更新流程适配到统一记忆管理器接口。

DeerMem 是自包含的默认 :class:`MemoryManager` 后端。

DeerMem 将 DeerFlow 的五个记忆模块（storage / queue / updater /
prompt / message_processing）封装在与后端无关的
:class:`~deerflow.agents.memory.manager.MemoryManager` 接口之后。
存储、队列及更新器是注入的实例属性，不使用模块级单例：工厂将 ``backend_config``
传给 ``__init__``，后者解析为 :class:`DeerMemConfig` 并构建依赖。
行为延续抽象前的代码：相同的消息过滤、人类与模型消息校验、纠正与强化检测结果
进入相同的防抖队列；``format_memory_for_injection`` 仍生成注入文本，
相同的增删改查流程继续支撑管理端点。

过滤与检测、``<memory>`` 包装、``enabled`` 门控及事实模型等 DeerMem 专属逻辑
保留在本后端中，不纳入抽象基类。抽象基类以外的 ``warm`` / ``create_fact`` /
``delete_fact`` / ``update_fact`` 方法供网关探测：
网关在启动时检查 ``hasattr(manager, "warm")``，并通过
``hasattr(manager, "create_fact")`` 检查事实增删改查能力，而不直接导入 DeerMem。
因此使用其他后端或移除该后端不会使这些模块在导入时失败（参见 MemoryManager 计划第 8 步）。
'''

from __future__ import annotations

import logging
from typing import Any

from deerflow.agents.memory.manager import MemoryManager

from .config import DeerMemConfig
from .llm import build_llm
from .message_processing import (
    detect_correction,
    detect_reinforcement,
    filter_messages_for_memory,
)
from .prompt import format_memory_for_injection, warm_tiktoken_cache
from .queue import MemoryUpdateQueue
from .storage import create_storage
from .updater import MemoryUpdater

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


    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        '''返回指定用户和代理的完整记忆数据。'''
        return self._updater.get_memory_data(agent_name=agent_name, user_id=user_id)


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


    def shutdown_flush(self, timeout: float) -> bool:
        '''在给定时限内同步刷新待处理记忆，供服务优雅关闭时尽量避免丢失更新。'''
        return self._queue.flush_sync(timeout)

    def warm(self) -> bool:
        '''若使用基于编码器的令牌计数，则提前加载其缓存；字符计数模式无需预热。'''
        if self._config.token_counting == "char":
            logger.info("token_counting='char'; tiktoken not used, skipping warm-up")
            return True
        return warm_tiktoken_cache()

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
