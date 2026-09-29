"""中和内置网络工具返回内容中的伪造框架标签，避免远程页面内容被误当成可信指令。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace as dc_replace
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

# 这些内置工具会返回可由远程网站影响的正文或状态文本，结果需经过净化。
#
# 当前按工具名白名单匹配，尚未覆盖使用任意名称注册的 MCP 网络工具。
# 不用名称片段猜测工具类型，避免误改本地搜索等可信工具的输出；后续应由注册元数据标记来源。
_REMOTE_CONTENT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "web_fetch",
        "web_search",
        "image_search",
        "web_capture",
    }
)


def _neutralize_content(content: object) -> object:
    """净化字符串或文本块并保持内容结构，图片等非文本块原样保留。"""
    # 延迟导入净化函数，避免模块初始化时形成不必要的依赖耦合。
    from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

    if isinstance(content, str):
        return neutralize_untrusted_tags(content)
    if isinstance(content, list):
        rebuilt: list[object] = []
        for block in content:
            if isinstance(block, str):
                rebuilt.append(neutralize_untrusted_tags(block))
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                rebuilt.append({**block, "text": neutralize_untrusted_tags(block["text"])})
            else:
                rebuilt.append(block)
        return rebuilt
    return content


def _sanitize_tool_message(message: ToolMessage) -> ToolMessage:
    """净化工具消息正文；内容未变化时返回原消息对象。"""
    new_content = _neutralize_content(message.content)
    if new_content == message.content:
        return message
    return message.model_copy(update={"content": new_content})


def _sanitize_result(result: ToolMessage | Command) -> ToolMessage | Command:
    """净化工具消息，或命令更新中的工具消息，并保留其他结果字段。"""
    if isinstance(result, ToolMessage):
        return _sanitize_tool_message(result)
    update = getattr(result, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages")
        if isinstance(messages, list) and any(isinstance(m, ToolMessage) for m in messages):
            new_messages = [_sanitize_tool_message(m) if isinstance(m, ToolMessage) else m for m in messages]
            if new_messages != messages:
                return dc_replace(result, update={**update, "messages": new_messages})
    return result


class ToolResultSanitizationMiddleware(AgentMiddleware[AgentState]):
    """只净化白名单内网络工具的结果；其他工具输出保持不变。"""

    def _should_sanitize(self, request: ToolCallRequest) -> bool:
        """根据工具名判断其结果是否来自需要净化的远程内容工具。"""
        return request.tool_call.get("name") in _REMOTE_CONTENT_TOOL_NAMES

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """同步执行工具调用，并按白名单净化远程工具结果。"""
        result = handler(request)
        if not self._should_sanitize(request):
            return result
        return _sanitize_result(result)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """异步执行工具调用，并按白名单净化远程工具结果。"""
        result = await handler(request)
        if not self._should_sanitize(request):
            return result
        return _sanitize_result(result)
