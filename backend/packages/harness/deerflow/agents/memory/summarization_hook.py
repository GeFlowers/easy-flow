"""提供摘要从状态移除消息前触发的记忆刷新钩子。"""

from __future__ import annotations

from deerflow.agents.memory import get_memory_manager
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import get_memory_config
from deerflow.runtime.user_context import resolve_runtime_user_id


def memory_flush_hook(event: SummarizationEvent) -> None:
    """将即将被摘要的消息立即刷新到记忆队列。

    此处只负责 ``enabled`` 与 ``thread_id`` 门控及用户标识解析；后端通过
    ``manager.add_nowait`` 完成消息筛选、用户与助手消息校验以及纠错、强化识别。
    """
    if not get_memory_config().enabled or not event.thread_id:
        return

    user_id = resolve_runtime_user_id(event.runtime)
    get_memory_manager().add_nowait(
        event.thread_id,
        list(event.messages_to_summarize),
        agent_name=event.agent_name,
        user_id=user_id,
    )
