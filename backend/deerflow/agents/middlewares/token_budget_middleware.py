'''按单次运行累计模型 令牌 用量，并在预算告警或硬上限处干预。

统计历史 AIMessage 的用量元数据，以增量方式处理后续补入的子代理用量。警告会在
下一次模型请求末尾注入，硬停止则移除工具调用使 智能体 返回已收集的结果。停止原因
会暂存到执行器读取，其他临时计数则在运行结束时清理。
'''

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.config.token_budget_config import TokenBudgetConfig

logger = logging.getLogger(__name__)

_BUDGET_WARNING_MSG = (
    "[TOKEN BUDGET WARNING] You have used {used:,} of your {budget:,} {reason} token budget ({percent:.0f}%). Wrap up your current work and produce a final answer. Avoid starting new tool calls unless absolutely necessary."
)
_BUDGET_EXCEEDED_MSG = "[TOKEN BUDGET EXCEEDED] The {reason} token usage ({used:,}) has exceeded the safety limit ({budget:,}). Producing final answer with results collected so far."


@dataclass
class TokenUsage:
    '''分别累计输入、输出和总 令牌 数。'''

    input: int = 0
    output: int = 0
    total: int = 0


class TokenBudgetMiddleware(AgentMiddleware[AgentState]):
    '''在 智能体 运行期间累计 令牌 用量，并实施软提醒和硬停止阈值。'''

    def __init__(self, config: TokenBudgetConfig) -> None:
        '''保存预算配置并初始化按 run_id 隔离的有界用量与提醒缓存。'''
        super().__init__()
        self._config = config
        self._lock = threading.Lock()

        # 按运行 ID 隔离状态，并限制缓存规模以防异常运行造成累积。
        self._warned: BoundedDict[str, bool] = BoundedDict(1000)
        self._pending_warnings: BoundedDict[str, list[str]] = BoundedDict(1000)
        self._seen_messages: BoundedDict[str, dict[str, tuple[int, int]]] = BoundedDict(1000)
        self._cumulative_usage: BoundedDict[str, TokenUsage] = BoundedDict(1000)
        # 停止原因要留给运行结束后的执行器读取，因此独立保留并设置容量上限。
        self._stop_reason: BoundedDict[str, str] = BoundedDict(1000)

    @classmethod
    def from_config(cls, config: TokenBudgetConfig) -> TokenBudgetMiddleware:
        '''根据已校验的 令牌 预算配置构造中间件。'''
        return cls(config=config)

    def reset(self) -> None:
        '''清空所有运行的累计用量、已发提醒和硬停止原因。'''
        with self._lock:
            self._warned.clear()
            self._pending_warnings.clear()
            self._seen_messages.clear()
            self._cumulative_usage.clear()
            self._stop_reason.clear()

    def consume_stop_reason(self, run_id: str | None) -> str | None:
        '''取出并删除本次运行的预算停止原因，供执行器标记被预算截断的子代理结果。'''
        with self._lock:
            return self._stop_reason.pop(run_id, None)

    @staticmethod
    def _get_run_id(runtime: Runtime) -> str:
        '''从运行上下文获取 ID；缺失时使用 Runtime 对象身份隔离嵌入式并发调用。'''
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict) and "run_id" in ctx:
            return ctx["run_id"]
        # 嵌入式调用未必有运行 ID，使用 Runtime 身份避免不同调用共用状态。
        return str(id(runtime))

    def _clear_run_state(self, run_id: str) -> None:
        '''清除指定运行的告警和用量状态，但保留供调用方读取的停止原因。'''
        with self._lock:
            self._warned.pop(run_id, None)
            self._pending_warnings.pop(run_id, None)
            self._seen_messages.pop(run_id, None)
            self._cumulative_usage.pop(run_id, None)

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> None:
        '''初始化本轮累计器，并将已有消息用量记为基线，不计入新运行预算。'''
        if not self._config.enabled:
            return

        # 已存在的对话消息属于此前运行，仅登记基线，避免重复计费。
        messages = state.get("messages", [])
        if not messages:
            return

        run_id = self._get_run_id(runtime)
        with self._lock:
            seen = self._seen_messages.setdefault(run_id, {})
            self._cumulative_usage.setdefault(run_id, TokenUsage())

            for msg in messages:
                if isinstance(msg, AIMessage) and msg.id and hasattr(msg, "usage_metadata"):
                    usage = msg.usage_metadata or {}
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    seen[msg.id] = (input_tokens, output_tokens)

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> None:
        '''异步启动钩子复用同步逻辑登记历史用量基线。'''
        self.before_agent(state, runtime)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> None:
        '''智能体 结束后释放本轮用量和警告缓存。'''
        if not self._config.enabled:
            return
        self._clear_run_state(self._get_run_id(runtime))

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> None:
        '''异步结束钩子复用同步清理逻辑。'''
        self.after_agent(state, runtime)

    @staticmethod
    def _append_text(content: str | list[dict | None] | None, stop_msg: str) -> str | list[dict | str]:
        '''按内容字段类型追加预算停止说明，兼容文本块列表和空内容。'''
        if content is None:
            return stop_msg
        if isinstance(content, str):
            if content:
                return f"{content}\n\n{stop_msg}"
            return f"\n\n{stop_msg}"
        if isinstance(content, list):
            new_content = list(content)
            new_content.append({"type": "text", "text": f"\n\n{stop_msg}"})
            return new_content
        return f"{content}\n\n{stop_msg}"

    def _build_hard_stop_update(self, msg: AIMessage, stop_msg: str) -> dict[str, Any]:
        '''创建硬停止状态更新，移除工具调用数据并规范化结束原因。'''
        updated_content = self._append_text(msg.content, stop_msg)
        kwargs = dict(msg.additional_kwargs) if msg.additional_kwargs else {}
        if "tool_calls" in kwargs:
            del kwargs["tool_calls"]
        if "function_call" in kwargs:
            del kwargs["function_call"]

        response_metadata = dict(getattr(msg, "response_metadata", {}) or {})

        if response_metadata.get("finish_reason") == "tool_calls":
            response_metadata["finish_reason"] = "stop"

        stopped_msg = msg.model_copy(update={"content": updated_content, "tool_calls": [], "additional_kwargs": kwargs, "response_metadata": response_metadata})
        return {"messages": [stopped_msg]}

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''汇总尚未计入的消息用量，选择最先达到的预算维度并生成警告或硬停止。'''
        if not self._config.enabled:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        run_id = self._get_run_id(runtime)

        with self._lock:
            seen = self._seen_messages.setdefault(run_id, {})
            usage_accum = self._cumulative_usage.setdefault(run_id, TokenUsage())

            for msg in messages:
                if isinstance(msg, AIMessage) and msg.id and hasattr(msg, "usage_metadata"):
                    usage = msg.usage_metadata or {}

                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)

                    # 按消息 ID 计算相对上次记录的新增用量。
                    prev_input, prev_output = seen.get(msg.id, (0, 0))

                    # 子代理用量可能稍后补写，因此只累计本次增加的差值。
                    diff_input = max(0, input_tokens - prev_input)
                    diff_output = max(0, output_tokens - prev_output)

                    if diff_input > 0 or diff_output > 0:
                        usage_accum.input += diff_input
                        usage_accum.output += diff_output
                        usage_accum.total += diff_input + diff_output
                        seen[msg.id] = (input_tokens, output_tokens)

            if usage_accum.total <= 0:
                return None

            fractions = [("total", usage_accum.total, self._config.max_tokens)]
            if self._config.max_input_tokens:
                fractions.append(("input", usage_accum.input, self._config.max_input_tokens))
            if self._config.max_output_tokens:
                fractions.append(("output", usage_accum.output, self._config.max_output_tokens))

            highest_fraction = 0.0
            trigger_reason = ""
            trigger_used = 0
            trigger_budget = 0

            for reason, used, limit in fractions:
                frac = used / limit
                if frac > highest_fraction:
                    highest_fraction = frac
                    trigger_reason = reason
                    trigger_used = used
                    trigger_budget = limit

            if highest_fraction >= self._config.hard_stop_threshold:
                logger.warning("Token budget hard stop triggered for run %s: %s limit exceeded", run_id, trigger_reason)
                # 硬停止通过正常返回结束图，因此额外记录原因供执行器区分预算截断。
                self._stop_reason[run_id] = "token_capped"
                # 同时写入运行上下文，便于 工作进程 无需中间件引用也能读取停止原因。
                ctx = getattr(runtime, "context", None)
                if isinstance(ctx, dict):
                    ctx["stop_reason"] = "token_capped"
                stop_text = _BUDGET_EXCEEDED_MSG.format(reason=trigger_reason, used=trigger_used, budget=trigger_budget)
                return self._build_hard_stop_update(last_msg, stop_text)

            if highest_fraction >= self._config.warn_threshold and not self._warned.get(run_id, False):
                self._warned[run_id] = True
                percent = highest_fraction * 100
                warn_text = _BUDGET_WARNING_MSG.format(reason=trigger_reason, used=trigger_used, budget=trigger_budget, percent=percent)
                logger.info("Token budget warning triggered for run %s: %s limit at %.1f%%", run_id, trigger_reason, percent)
                # 等待模型调用包装器追加提示，避免改变当前图状态。
                warnings = self._pending_warnings.setdefault(run_id, [])
                warnings.append(warn_text)
                return None

            return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''模型返回后更新 令牌 用量并检查预算阈值。'''
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        '''异步模型返回后执行相同的用量统计与阈值检查。'''
        return self._apply(state, runtime)

    def _drain_pending_warnings(self, runtime: Runtime) -> list[str]:
        '''取出并删除本轮待注入的预算提醒；预算功能关闭时返回空列表。'''
        if not self._config.enabled:
            return []

        run_id = self._get_run_id(runtime)
        with self._lock:
            warnings = self._pending_warnings.pop(run_id, None)
        return warnings or []

    def _inject_warnings(self, request: ModelRequest, warnings: list[str]) -> ModelRequest:
        '''将合并后的预算提醒追加到模型请求；无提醒时保持原请求不变。'''
        if not warnings:
            return request

        merged_text = "\n\n".join(warnings)
        warning_msg = HumanMessage(content=merged_text, name="budget_warning")

        messages = getattr(request, "messages", [])
        new_messages = list(messages) + [warning_msg]
        return request.override(messages=new_messages)

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        '''同步模型调用前注入暂存提醒，再调用下游模型处理器。'''
        warnings = self._drain_pending_warnings(request.runtime)
        request = self._inject_warnings(request, warnings)

        return handler(request)

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        '''异步模型调用前注入暂存提醒，再等待下游模型处理器。'''
        warnings = self._drain_pending_warnings(request.runtime)
        request = self._inject_warnings(request, warnings)
        return await handler(request)
