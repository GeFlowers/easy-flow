'''在代理运行结束后将本轮对话交给记忆管理器，由其筛选并排队处理可保留的对话内容。'''

import logging
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.memory import get_memory_manager
from deerflow.config.memory_config import get_memory_config
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, normalize_trace_id

if TYPE_CHECKING:
    from deerflow.config.memory_config import MemoryConfig

logger = logging.getLogger(__name__)


class MemoryMiddlewareState(AgentState):
    '''复用代理线程状态结构，供记忆中间件读取本轮消息。'''

    pass


class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    '''代理执行完成后采集线程、用户及追踪上下文，并将消息交由记忆后端过滤和异步排队。'''

    state_schema = MemoryMiddlewareState

    def __init__(self, agent_name: str | None = None, *, memory_config: "MemoryConfig | None" = None):
        '''保存可选的代理名称和记忆配置；未显式传入配置时使用全局记忆配置。'''
        super().__init__()
        self._agent_name = agent_name
        self._memory_config = memory_config

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        '''检查记忆是否启用并取得线程、用户和追踪标识，再将本轮消息交给记忆管理器。'''
        config = self._memory_config or get_memory_config()
        if not config.enabled:
            return None

        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id is None:
            config_data = get_config()
            thread_id = config_data.get("configurable", {}).get("thread_id")
        if not thread_id:
            logger.debug("No thread_id in context, skipping memory update")
            return None

        messages = state.get("messages", [])
        if not messages:
            logger.debug("No messages in state, skipping memory update")
            return None

        user_id = get_effective_user_id()
        runtime_context = runtime.context if isinstance(runtime.context, dict) else {}
        trace_id = normalize_trace_id(runtime_context.get(DEERFLOW_TRACE_METADATA_KEY))
        if trace_id is None:
            try:
                config_data = get_config()
            except RuntimeError:
                config_data = {}
            config_metadata = config_data.get("metadata", {}) if isinstance(config_data.get("metadata"), dict) else {}
            trace_id = normalize_trace_id(config_metadata.get(DEERFLOW_TRACE_METADATA_KEY))
        if trace_id is None:
            trace_id = get_current_trace_id()

        get_memory_manager().add(
            thread_id,
            messages,
            agent_name=self._agent_name,
            user_id=user_id,
            trace_id=trace_id,
        )

        return None
