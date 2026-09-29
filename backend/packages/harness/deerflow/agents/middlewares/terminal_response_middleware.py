"""确保工具执行后的 Agent 轮次最终留下用户可见的助手答复。"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse, hook_config
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict

_RECOVERY_PROMPT = (
    "<system_reminder>\n"
    "Your previous response after the tool execution was empty. Review the tool results "
    "already present in the conversation and provide a concise, user-visible final response. "
    "Do not call another tool unless it is strictly necessary.\n"
    "</system_reminder>"
)

_FALLBACK_CONTENT = "The model completed the tool run but returned no final response, including after one automatic retry. Please try again or use a different model."

_TOOL_CALL_FINISH_REASONS = {"tool_calls", "function_call"}


def _has_visible_content(message: AIMessage) -> bool:
    """判断 AIMessage 是否包含可展示的文本内容块。"""
    content = message.content
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str) and block.strip():
                return True
            if isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return True
    return False


def _has_tool_call_intent_or_error(message: AIMessage) -> bool:
    """检查消息是否仍表达工具调用或工具解析错误，而非最终答复。"""
    if message.tool_calls or getattr(message, "invalid_tool_calls", None):
        return True
    additional_kwargs = message.additional_kwargs or {}
    if additional_kwargs.get("tool_calls") or additional_kwargs.get("function_call"):
        return True
    response_metadata = message.response_metadata or {}
    return response_metadata.get("finish_reason") in _TOOL_CALL_FINISH_REASONS


def _tool_result_in_current_turn(messages: list[Any]) -> bool:
    """判断最近一条真实用户消息之后是否出现工具结果。"""
    latest_user_index = -1
    for index, message in enumerate(messages):
        if not isinstance(message, HumanMessage):
            continue
        if (message.additional_kwargs or {}).get("hide_from_ui"):
            continue
        latest_user_index = index
    # 只对交互式用户轮次执行恢复；内部调度由其自身的成功条件判断。
    if latest_user_index == -1:
        return False
    return any(isinstance(message, ToolMessage) for message in messages[latest_user_index + 1 :])


class TerminalResponseMiddleware(AgentMiddleware[AgentState]):
    """工具结果后若模型返回空答复则重试一次，仍为空时写入可见错误说明。"""

    def __init__(self) -> None:
        """初始化按线程和运行隔离且有界的重试计数与提示标记。"""
        super().__init__()
        self._lock = threading.Lock()
        self._retry_counts: BoundedDict[tuple[str, str], int] = BoundedDict(1000)
        self._pending_prompts: BoundedDict[tuple[str, str], bool] = BoundedDict(1000)

    @staticmethod
    def _key(runtime: Runtime) -> tuple[str, str]:
        """从运行上下文生成线程与运行组合键，缺字段时使用安全回退值。"""
        context = getattr(runtime, "context", None)
        if isinstance(context, dict):
            thread_id = str(context.get("thread_id") or "unknown-thread")
            run_id = str(context.get("run_id") or context.get("run_attempt_id") or id(runtime))
            return thread_id, run_id
        # 测试和自定义嵌入调用可能没有标准 Runtime 上下文。
        return "unknown-thread", str(id(runtime))

    def _clear(self, runtime: Runtime) -> None:
        """清除当前运行的重试预算和待注入提示。"""
        key = self._key(runtime)
        with self._lock:
            self._retry_counts.pop(key, None)
            self._pending_prompts.pop(key, None)

    def _clear_other_runs(self, runtime: Runtime) -> None:
        """清除同一线程其他运行遗留的重试状态。"""
        thread_id, run_id = self._key(runtime)
        with self._lock:
            stale = [key for key in self._retry_counts if key[0] == thread_id and key[1] != run_id]
            for key in stale:
                self._retry_counts.pop(key, None)
                self._pending_prompts.pop(key, None)

    def _apply(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """仅处理工具结果后的空终态：首次跳回模型，重试仍为空则替换为错误答复。"""
        messages = list(state.get("messages") or [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None

        last = messages[-1]
        if _has_visible_content(last) or _has_tool_call_intent_or_error(last):
            return None
        if not _tool_result_in_current_turn(messages):
            return None

        key = self._key(runtime)
        with self._lock:
            # 重试额度按运行计算，不能因重试期间又调用工具而反复刷新。
            retry_count = self._retry_counts.get(key, 0)
            if retry_count == 0:
                self._retry_counts[key] = 1
                self._pending_prompts[key] = True

        if retry_count == 0:
            # 在重试前移除空消息，避免恢复成功后空终态进入检查点或后续上下文。
            message_updates = [RemoveMessage(id=last.id)] if last.id else []
            return {"messages": message_updates, "jump_to": "model"}

        additional_kwargs = dict(last.additional_kwargs or {})
        additional_kwargs.update(
            {
                "deerflow_error_fallback": True,
                "error_reason": "Model returned an empty terminal response after one retry",
            }
        )
        fallback = last.model_copy(
            update={
                "content": _FALLBACK_CONTENT,
                "additional_kwargs": additional_kwargs,
            }
        )
        return {"messages": [fallback]}

    def _augment_request(self, request: ModelRequest) -> ModelRequest:
        """消费当前运行的重试标记，并在模型请求末尾追加隐藏恢复提示。"""
        key = self._key(request.runtime)
        with self._lock:
            pending = key in self._pending_prompts
            self._pending_prompts.pop(key, None)
        if not pending:
            return request
        reminder = HumanMessage(
            content=_RECOVERY_PROMPT,
            name="terminal_response_recovery",
            additional_kwargs={"hide_from_ui": True},
        )
        return request.override(messages=[*request.messages, reminder])

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        """启动新运行时清理旧运行状态并重置本轮唯一一次的恢复额度。"""
        self._clear_other_runs(runtime)
        # 上次执行可能通过跳转结束而未触发 after_agent，因此在新入口重置重试额度。
        self._clear(runtime)
        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        """异步启动钩子清除过期运行状态并初始化新的重试额度。"""
        self._clear_other_runs(runtime)
        self._clear(runtime)
        return None

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """同步模型返回后判断是否需要一次性恢复。"""
        return self._apply(state, runtime)

    @hook_config(can_jump_to=["model"])
    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """异步模型返回后复用相同的空答复检测与恢复逻辑。"""
        return self._apply(state, runtime)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """同步模型请求前注入恢复提示，再调用后续处理器。"""
        return handler(self._augment_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """异步模型请求前注入恢复提示，再等待后续处理器。"""
        return await handler(self._augment_request(request))

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        """运行正常结束后清除本轮重试状态。"""
        self._clear(runtime)
        return None

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        """异步运行结束后清除本轮重试状态。"""
        self._clear(runtime)
        return None
