'''工具搜索启用时，在模型发现工具前隐藏其参数结构并阻止提前调用。

此中间件从模型绑定中筛除延迟工具的参数结构。

启用 tool_search 时，MCP 工具仍会交给 ToolNode 执行，但模型通过 tool_search
发现工具之前，不得通过 bind_tools 将其参数结构发送给模型。此中间件在模型绑定前
从 request.tools 移除仍处于延迟状态的工具，并阻止调用尚未提升的工具。

延迟工具名称集合与目录哈希值在构造时注入，不使用 ContextVar。
提升状态从图状态（``state["promoted"]``）读取，并按目录哈希值限定作用范围，
防止过期的持久化提升记录暴露已更名或已发生变化的工具。
'''

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class DeferredToolFilterMiddleware(AgentMiddleware[AgentState]):
    '''按工具目录版本筛选模型可见工具，并拦截尚未提升的延迟工具调用。

    延迟工具提升前，其参数结构对绑定的模型不可见。

        ToolNode 仍持有所有工具（包括延迟工具）以供执行路由，但模型只能看到
        活跃工具及已提升工具的参数结构；提升记录保存在当前目录哈希值对应的
        ``state["promoted"]`` 中。
    '''

    def __init__(self, deferred_names: frozenset[str], catalog_hash: str | None):
        '''使用延迟工具名称集合及其目录版本标识初始化过滤器。'''
        super().__init__()
        self._deferred = deferred_names
        self._catalog_hash = catalog_hash

    def _promoted(self, state) -> set[str]:
        '''从当前目录版本对应的状态中取得已提升工具名称。'''
        promoted = (state or {}).get("promoted")
        if promoted and promoted.get("catalog_hash") == self._catalog_hash:
            return set(promoted.get("names") or [])
        return set()

    def _hidden(self, state) -> set[str]:
        '''计算当前仍应对模型隐藏的延迟工具名称。'''
        return set(self._deferred) - self._promoted(state)

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        '''从模型请求中移除尚未提升的延迟工具参数结构。'''
        if not self._deferred:
            return request
        hide = self._hidden(request.state)
        if not hide:
            return request
        active = [t for t in request.tools if getattr(t, "name", None) not in hide]
        if len(active) < len(request.tools):
            logger.debug("Filtered %d deferred tool schema(s) from model binding", len(request.tools) - len(active))
        return request.override(tools=active)

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage | None:
        '''为尚未提升的延迟工具调用生成阻止消息，或返回 None。'''
        if not self._deferred:
            return None
        name = str(request.tool_call.get("name") or "")
        if not name or name not in self._hidden(request.state):
            return None
        tool_call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
        return ToolMessage(
            content=(f"Error: Tool '{name}' is deferred and has not been promoted yet. Call tool_search first to expose and promote this tool's schema, then retry."),
            tool_call_id=tool_call_id,
            name=name,
            status="error",
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        '''过滤同步模型调用可见的工具后执行后续处理器。'''
        return handler(self._filter_tools(request))

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        '''阻止未提升的工具调用，其余调用交由后续处理器执行。'''
        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        '''过滤异步模型调用可见的工具后等待后续处理器执行。'''
        return await handler(self._filter_tools(request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        '''异步阻止未提升的工具调用，或等待后续处理器执行。'''
        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return await handler(request)
