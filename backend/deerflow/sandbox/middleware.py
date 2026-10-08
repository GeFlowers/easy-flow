'''在智能体和工具调用生命周期中管理沙箱的中间件。'''

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace as dc_replace
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from deerflow.agents.thread_state import SandboxStateField, ThreadDataState
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox import get_sandbox_provider

logger = logging.getLogger(__name__)


class SandboxMiddlewareState(AgentState):
    '''声明沙箱中间件读取和写入的智能体状态字段。'''

    sandbox: SandboxStateField
    thread_data: NotRequired[ThreadDataState | None]


class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    '''按需获取、传播并在运行结束时释放线程范围内的沙箱。'''

    state_schema = SandboxMiddlewareState

    def __init__(self, lazy_init: bool = True):
        '''初始化中间件，并配置是否延迟获取沙箱。'''
        super().__init__()
        self._lazy_init = lazy_init

    def _acquire_sandbox(self, thread_id: str, *, user_id: str) -> str:
        '''同步获取指定线程和用户范围内的沙箱标识。'''
        provider = get_sandbox_provider()
        sandbox_id = provider.acquire(thread_id, user_id=user_id)
        logger.info(f"Acquiring sandbox {sandbox_id}")
        return sandbox_id

    async def _acquire_sandbox_async(self, thread_id: str, *, user_id: str) -> str:
        '''异步获取指定线程和用户范围内的沙箱标识。'''
        provider = get_sandbox_provider()
        sandbox_id = await provider.acquire_async(thread_id, user_id=user_id)
        logger.info(f"Acquiring sandbox {sandbox_id}")
        return sandbox_id

    async def _release_sandbox_async(self, sandbox_id: str) -> None:
        '''在线程中异步释放指定沙箱，避免阻塞事件循环。'''
        await asyncio.to_thread(get_sandbox_provider().release, sandbox_id)

    @override
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        '''在同步智能体运行前按配置预先分配沙箱。'''
        if self._lazy_init:
            return super().before_agent(state, runtime)

        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = (runtime.context or {}).get("thread_id")
            if thread_id is None:
                return super().before_agent(state, runtime)
            sandbox_id = self._acquire_sandbox(thread_id, user_id=resolve_runtime_user_id(runtime))
            logger.info(f"Assigned sandbox {sandbox_id} to thread {thread_id}")
            return {"sandbox": {"sandbox_id": sandbox_id}}
        return super().before_agent(state, runtime)

    @override
    async def abefore_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        '''在异步智能体运行前按配置预先分配沙箱。'''
        if self._lazy_init:
            return await super().abefore_agent(state, runtime)

        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = (runtime.context or {}).get("thread_id")
            if thread_id is None:
                return await super().abefore_agent(state, runtime)
            sandbox_id = await self._acquire_sandbox_async(thread_id, user_id=resolve_runtime_user_id(runtime))
            logger.info(f"Assigned sandbox {sandbox_id} to thread {thread_id}")
            return {"sandbox": {"sandbox_id": sandbox_id}}
        return await super().abefore_agent(state, runtime)

    @override
    def after_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        '''在同步智能体运行结束后释放状态或上下文中的沙箱。'''
        sandbox = state.get("sandbox")
        if sandbox is not None:
            sandbox_id = sandbox["sandbox_id"]
            logger.info(f"Releasing sandbox {sandbox_id}")
            get_sandbox_provider().release(sandbox_id)
            return None

        if (runtime.context or {}).get("sandbox_id") is not None:
            sandbox_id = runtime.context.get("sandbox_id")
            logger.info(f"Releasing sandbox {sandbox_id} from context")
            get_sandbox_provider().release(sandbox_id)
            return None

        return super().after_agent(state, runtime)

    @override
    async def aafter_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        '''在异步智能体运行结束后释放状态或上下文中的沙箱。'''
        sandbox = state.get("sandbox")
        if sandbox is not None:
            sandbox_id = sandbox["sandbox_id"]
            logger.info(f"Releasing sandbox {sandbox_id}")
            await self._release_sandbox_async(sandbox_id)
            return None

        if (runtime.context or {}).get("sandbox_id") is not None:
            sandbox_id = runtime.context.get("sandbox_id")
            logger.info(f"Releasing sandbox {sandbox_id} from context")
            await self._release_sandbox_async(sandbox_id)
            return None

        return await super().aafter_agent(state, runtime)


    @staticmethod
    def _read_sandbox_id_from_state(state: object) -> str | None:
        '''从字典形态的状态中安全提取沙箱标识。'''
        if not isinstance(state, dict):
            return None
        sandbox_state = state.get("sandbox")
        if not isinstance(sandbox_state, dict):
            return None
        sandbox_id = sandbox_state.get("sandbox_id")
        return sandbox_id if isinstance(sandbox_id, str) else None

    @staticmethod
    def _attach_sandbox_update(result: ToolMessage | Command, sandbox_id: str) -> ToolMessage | Command:
        '''将新获得的沙箱标识合并到工具结果的状态更新中。'''
        sandbox_update = {"sandbox": {"sandbox_id": sandbox_id}}

        if isinstance(result, ToolMessage):
            return Command(update={**sandbox_update, "messages": [result]})

        existing_update = result.update
        if isinstance(existing_update, dict):
            merged_update = {**existing_update, **sandbox_update}
            return dc_replace(result, update=merged_update)
        return result

    @staticmethod
    def _read_sandbox_id_from_request(request: ToolCallRequest) -> str | None:
        '''从工具调用请求的运行时状态中读取沙箱标识。'''
        runtime = request.runtime
        if runtime is None or runtime.state is None:
            return None
        return SandboxMiddleware._read_sandbox_id_from_state(runtime.state)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        '''执行同步工具调用，并把调用期间延迟初始化的沙箱写回结果。'''
        prev_sandbox_id = self._read_sandbox_id_from_request(request)
        result = handler(request)
        if prev_sandbox_id is not None:
            return result
        curr_sandbox_id = self._read_sandbox_id_from_request(request)
        if curr_sandbox_id is None:
            return result
        return self._attach_sandbox_update(result, curr_sandbox_id)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        '''执行异步工具调用，并把调用期间延迟初始化的沙箱写回结果。'''
        prev_sandbox_id = self._read_sandbox_id_from_request(request)
        result = await handler(request)
        if prev_sandbox_id is not None:
            return result
        curr_sandbox_id = self._read_sandbox_id_from_request(request)
        if curr_sandbox_id is None:
            return result
        return self._attach_sandbox_update(result, curr_sandbox_id)
