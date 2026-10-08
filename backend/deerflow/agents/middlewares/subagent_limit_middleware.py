'''限制每次模型回复及单次运行可以发起的子代理任务数量。'''

import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.config.subagents_config import (
    DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN,
    MAX_CONCURRENT_SUBAGENT_CALLS,
    MAX_TOTAL_SUBAGENTS_PER_RUN,
    MIN_CONCURRENT_SUBAGENT_CALLS,
    MIN_TOTAL_SUBAGENTS_PER_RUN,
    clamp_subagent_concurrency,
    clamp_total_subagents_per_run,
)
from deerflow.subagents.executor import MAX_CONCURRENT_SUBAGENTS

logger = logging.getLogger(__name__)

MIN_SUBAGENT_LIMIT = MIN_CONCURRENT_SUBAGENT_CALLS
MAX_SUBAGENT_LIMIT = MAX_CONCURRENT_SUBAGENT_CALLS
DEFAULT_MAX_TOTAL_SUBAGENTS = DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN
MIN_SUBAGENT_TOTAL_LIMIT = MIN_TOTAL_SUBAGENTS_PER_RUN
MAX_SUBAGENT_TOTAL_LIMIT = MAX_TOTAL_SUBAGENTS_PER_RUN

_TOTAL_LIMIT_STOP_MSG = (
    "[SUBAGENT LIMIT REACHED] The subagent delegation limit for this run has been reached. "
    "Continue using the subagent results already collected, execute remaining simple work "
    "directly, or summarize the remaining work instead of launching more subagents."
)


def _clamp_subagent_limit(value: int) -> int:
    '''将并发子代理数量限制在应用支持的配置范围内。'''
    return clamp_subagent_concurrency(value)


def _clamp_total_subagent_limit(value: int) -> int:
    '''将单次运行的子代理总数限制在允许的正整数范围内。'''
    return clamp_total_subagents_per_run(value)


def _append_text(content: Any, text: str) -> Any:
    '''按消息内容类型追加总量上限提示，并保留多模态内容列表结构。'''
    if content is None:
        return text
    if isinstance(content, str):
        if content:
            return f"{content}\n\n{text}"
        return text
    if isinstance(content, list):
        return [*content, {"type": "text", "text": f"\n\n{text}"}]
    return f"{content}\n\n{text}"


def _delegation_id(entry: object) -> str | None:
    '''从委派记录中读取并规范化委派标识。'''
    if not isinstance(entry, dict):
        return None
    entry_id = entry.get("id")
    return str(entry_id) if entry_id else None


def _delegation_run_id(entry: object) -> str | None:
    '''从委派记录中读取并规范化运行标识。'''
    if not isinstance(entry, dict):
        return None
    run_id = entry.get("run_id")
    return str(run_id) if run_id else None


def _runtime_run_id(runtime: Runtime | None) -> str | None:
    '''从运行时上下文读取当前运行标识。'''
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict):
        return None
    run_id = context.get("run_id")
    return str(run_id) if run_id else None


def _count_prior_delegations(delegations: object, *, run_id: str | None) -> int:
    '''统计当前运行中不同的既有子代理委派数量。'''
    if not isinstance(delegations, list):
        return 0
    ids = set()
    for entry in delegations:
        if run_id is not None and _delegation_run_id(entry) != run_id:
            continue
        delegation_id = _delegation_id(entry)
        if delegation_id is not None:
            ids.add(delegation_id)
    return len(ids)


class SubagentLimitMiddleware(AgentMiddleware[AgentState]):
    '''按并发上限和持久化委派账本中的本轮调用数修剪超额 task 工具调用。'''

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_SUBAGENTS, max_total: int = DEFAULT_MAX_TOTAL_SUBAGENTS):
        '''保存经配置范围校验后的并发调用上限和单次运行总调用上限。'''
        super().__init__()
        self.max_concurrent = _clamp_subagent_limit(max_concurrent)
        self.max_total = _clamp_total_subagent_limit(max_total)

    def _truncate_task_calls(self, state: AgentState, runtime: Runtime | None = None) -> dict | None:
        '''检查最后一条模型消息中的 task 调用数，移除超过并发或本轮总额的调用。'''
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        task_indices = [i for i, tc in enumerate(tool_calls) if tc.get("name") == "task"]
        if not task_indices:
            return None

        run_id = _runtime_run_id(runtime)
        if run_id is None:
            logger.warning("Subagent limit middleware received no run_id; counting all thread delegations as prior usage. Pass run_id in runtime context to enforce the total cap per run.")
        prior_delegation_count = _count_prior_delegations(state.get("delegations"), run_id=run_id)
        remaining_total = max(0, self.max_total - prior_delegation_count)
        allowed_task_calls = min(self.max_concurrent, remaining_total)

        if len(task_indices) <= allowed_task_calls:
            return None

        indices_to_drop = set(task_indices[allowed_task_calls:])
        truncated_tool_calls = [tc for i, tc in enumerate(tool_calls) if i not in indices_to_drop]
        dropped_count = len(indices_to_drop)
        logger.warning(
            "Truncated %s excess task tool call(s) from model response (concurrent limit: %s; total limit: %s; prior delegations: %s)",
            dropped_count,
            self.max_concurrent,
            self.max_total,
            prior_delegation_count,
        )

        if remaining_total == 0 and isinstance(getattr(runtime, "context", None), dict):
            runtime.context["stop_reason"] = "subagent_limit_capped"

        content = _append_text(last_msg.content, _TOTAL_LIMIT_STOP_MSG) if remaining_total == 0 else None
        updated_msg = clone_ai_message_with_tool_calls(last_msg, truncated_tool_calls, content=content)
        return {"messages": [updated_msg]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''在同步模型返回后应用子代理调用上限。'''
        return self._truncate_task_calls(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''在异步模型返回后应用同一套子代理调用上限。'''
        return self._truncate_task_calls(state, runtime)
