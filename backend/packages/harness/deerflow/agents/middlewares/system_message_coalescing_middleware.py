'''在模型请求发送前合并静态提示和历史中的系统消息，避免供应方拒绝分散的系统指令。'''

from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from deerflow.agents.middlewares.dynamic_context_middleware import is_dynamic_context_reminder


def _flatten_content(content) -> str:
    '''将字符串或多模态内容片段整理为纯文本，供系统消息合并使用。'''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _coalesce_request(request: ModelRequest) -> ModelRequest | None:
    '''合并请求字段和消息列表中的系统消息，去除过期日期提醒并保留首条消息标识。'''
    in_msg_systems = [m for m in request.messages if isinstance(m, SystemMessage)]
    if not in_msg_systems:
        return None

    parts: list[SystemMessage] = []
    if request.system_message is not None:
        parts.append(request.system_message)
    parts.extend(in_msg_systems)

    reminder_indices = [i for i, p in enumerate(parts) if is_dynamic_context_reminder(p)]
    if len(reminder_indices) > 1:
        keep_last = reminder_indices[-1]
        parts = [p for i, p in enumerate(parts) if i not in reminder_indices[:-1] or i == keep_last]

    first = parts[0]
    merged_kwargs: dict = {}
    for p in parts:
        merged_kwargs.update(p.additional_kwargs or {})
    merged = SystemMessage(
        content="\n\n".join(_flatten_content(p.content) for p in parts),
        id=first.id,
        additional_kwargs=merged_kwargs,
    )

    non_system = [m for m in request.messages if not isinstance(m, SystemMessage)]
    return request.override(system_message=merged, messages=non_system)


class SystemMessageCoalescingMiddleware(AgentMiddleware[AgentState]):
    '''只修改发往模型的请求对象，不改写持久化消息历史中的系统消息。'''

    @staticmethod
    def _maybe_coalesce(request: ModelRequest) -> ModelRequest:
        '''在存在分散系统消息时返回合并后的请求，否则保留原请求对象。'''
        coalesced = _coalesce_request(request)
        if coalesced is None:
            return request
        return coalesced

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        '''在同步模型处理器运行前合并系统消息。'''
        return handler(self._maybe_coalesce(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        '''在异步模型处理器运行前合并系统消息。'''
        return await handler(self._maybe_coalesce(request))
