'''拦截 Agent 的澄清工具调用，并将问题转换为可供界面展示的中断消息。'''

import json
import logging
from collections.abc import Callable
from hashlib import sha256
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ClarificationMiddlewareState(AgentState):
    '''与线程状态兼容的澄清中间件状态类型。'''

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    '''将 `ask_clarification` 调用转成可见问题并结束当前图运行，等待用户后续回复。'''

    state_schema = ClarificationMiddlewareState

    def _stable_message_id(self, tool_call_id: str, formatted_message: str) -> str:
        '''依据工具调用 ID 或消息摘要生成稳定 ID，避免重试重复追加问题。'''
        if tool_call_id:
            return f"clarification:{tool_call_id}"
        digest = sha256(formatted_message.encode("utf-8")).hexdigest()[:16]
        return f"clarification:{digest}"

    def _normalize_options(self, raw_options: Any) -> list[str]:
        '''把工具参数中的选项统一转换为字符串列表，兼容 JSON 字符串形式。'''
        options = raw_options

        # 部分模型会把数组参数序列化为 JSON 字符串；在界面渲染前统一还原为列表。
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (json.JSONDecodeError, TypeError):
                options = [options]

        if options is None:
            return []
        if not isinstance(options, list):
            options = [options]

        return [str(option) for option in options]

    def _build_human_input_payload(self, args: dict[str, Any], *, tool_call_id: str, request_id: str) -> dict[str, Any]:
        '''生成前端识别的结构化用户输入载荷，同时保留可读文本作为兼容展示。'''
        options = self._normalize_options(args.get("options", []))
        clarification_type = str(args.get("clarification_type", "missing_info"))

        payload: dict[str, Any] = {
            "version": 1,
            "kind": "human_input_request",
            "source": "ask_clarification",
            "request_id": request_id,
            "clarification_type": clarification_type,
            "question": str(args.get("question") or ""),
            "input_mode": "choice_with_other" if options else "free_text",
        }

        if tool_call_id:
            payload["tool_call_id"] = tool_call_id

        if "context" in args:
            context = args.get("context")
            payload["context"] = None if context is None else str(context)

        if options:
            payload["options"] = [
                {
                    "id": f"option-{index}",
                    "label": option,
                    "value": option,
                }
                for index, option in enumerate(options, 1)
            ]

        return payload

    def _is_chinese(self, text: str) -> bool:
        '''检查文本中是否包含中日韩统一表意文字区的汉字。'''
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict) -> str:
        '''按澄清类型添加图标，并组合背景、问题和可选项供用户阅读。'''
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = self._normalize_options(args.get("options", []))

        # 按澄清类型选择提示图标。
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        # 组合成自然阅读顺序。
        message_parts = []

        # 有背景时先展示背景，再单独显示问题。
        if context:
            # 先呈现背景，再提出具体问题。
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            # 没有背景时直接显示问题。
            message_parts.append(f"{icon} {question}")

        # 将选项按编号列出。
        if options and len(options) > 0:
            message_parts.append("")  # 空行用于分隔问题和选项。
            for i, option in enumerate(options, 1):
                message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    def _is_disabled(self, request: ToolCallRequest) -> bool:
        '''检查当前运行上下文是否禁止交互式澄清。'''
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        if not context:
            return False
        return bool(context.get("disable_clarification"))

    def _handle_disabled_clarification(self, request: ToolCallRequest) -> ToolMessage:
        '''在非交互运行中不打断流程，而是要求 Agent 基于合理假设继续执行。'''
        tool_call_id = request.tool_call.get("id", "")
        logger.info("ask_clarification suppressed (disable_clarification set); instructing agent to proceed")
        return ToolMessage(
            id=self._stable_message_id(tool_call_id, "proceed-without-clarification"),
            content=(
                "Clarification is disabled in this context — the human is not present "
                "to answer synchronously. Do not ask for confirmation. Proceed with your "
                "best judgment, carry out the requested action, and state any assumptions "
                "you made in your final response."
            ),
            tool_call_id=tool_call_id,
            name="ask_clarification",
        )

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        '''构造带结构化 UI 数据的工具消息，并通过图命令结束当前运行。'''
        # 读取模型传入的澄清问题和选项。
        args = request.tool_call.get("args", {})
        question = args.get("question", "")

        logger.info("Intercepted clarification request")
        logger.debug("Clarification question: %s", question)

        # 生成用户可直接阅读的问题文本。
        formatted_message = self._format_clarification_message(args)

        # 读取工具调用标识。
        tool_call_id = request.tool_call.get("id", "")

        request_id = self._stable_message_id(tool_call_id, formatted_message)
        human_input_payload = self._build_human_input_payload(args, tool_call_id=tool_call_id, request_id=request_id)

        # 将澄清文本和前端结构化载荷写入消息历史。
        tool_message = ToolMessage(
            id=request_id,
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
            artifact={"human_input": human_input_payload},
        )

        # 追加工具消息并结束当前图运行；前端会直接识别并展示该澄清消息。
        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        '''同步拦截澄清工具调用；其他工具仍交由原处理器执行。'''
        if request.tool_call.get("name") != "ask_clarification":
            # 非澄清工具保持原有执行路径。
            return handler(request)

        if self._is_disabled(request):
            return self._handle_disabled_clarification(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        '''异步拦截澄清工具调用；其他工具通过异步原处理器继续执行。'''
        if request.tool_call.get("name") != "ask_clarification":
            # 非澄清工具保持原有异步执行路径。
            return await handler(request)

        if self._is_disabled(request):
            return self._handle_disabled_clarification(request)

        return self._handle_clarification(request)
