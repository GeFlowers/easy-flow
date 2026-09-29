"""在模型调用前中和用户文本中的伪造控制标签，并用边界标记隔离原始输入。"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphBubbleUp

from deerflow.agents.human_input import read_human_input_response
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY, message_content_to_text

logger = logging.getLogger(__name__)

_SUMMARY_MESSAGE_NAME = "summary"

# 拒绝列表包含框架保留标签和常见提示注入标签。
_BLOCKED_TAG_NAMES: frozenset[str] = frozenset(
    {
        # 覆盖框架实际注入模型上下文的全部权威标签，避免不可信消息伪造内部提示块。
        # system-reminder 与 system_reminder 是不同中间件使用的两种拼写。
        #
        # 子代理复用同一组基础中间件，因此其系统提示标签也必须纳入保护范围。
        "system-reminder",
        "system_reminder",
        "memory",
        "current_date",
        "think",
        "analysis",
        "role",
        "soul",
        "self_update",
        "thinking_style",
        "clarification_system",
        "critical_reminders",
        "response_style",
        "citations",
        "subagent_system",
        "skill_system",
        "skill_index",
        "available_skills",
        "disabled_skills",
        "memory_tool_system",
        "uploaded_files",
        "todo_list_system",
        "durable_context_data",
        "slash_skill_activation",
        "mcp_routing_hints",
        "available-deferred-tools",
        "goal_continuation",
        "file_editing_workflow",
        "guidelines",
        "output_format",
        "working_directory",
        # 子代理提示块用于声明 task 工具限制，伪造该标签会误导模型对权限的判断。
        "tool_restrictions",
        # 常见提示注入标签。
        "system",
        "instruction",
        "important",
        "override",
        "ignore",
        "prompt",
    }
)

# 匹配完整或不完整的被拒绝标签，包括闭合标签和带属性标签。
_BLOCKED_TAG_PATTERN = re.compile(
    r"<\s*/?\s*(?:" + "|".join(re.escape(t) for t in sorted(_BLOCKED_TAG_NAMES)) + r")\b[^>]*>?",
    re.IGNORECASE,
)

# 用户文本的纯文本边界标记，用于区分数据与指令。
_USER_INPUT_BEGIN = "--- BEGIN USER INPUT ---"
_USER_INPUT_END = "--- END USER INPUT ---"

# 用户文本若包含真实边界标记，则改成外观相近但无法匹配的中和形式。
_NEUTRALIZED_BEGIN = "[BEGIN USER INPUT]"
_NEUTRALIZED_END = "[END USER INPUT]"

# 匹配正文中任意位置出现的真实边界标记。
_BOUNDARY_TOKEN_RE = re.compile(
    re.escape(_USER_INPUT_BEGIN) + r"|" + re.escape(_USER_INPUT_END),
)


def _escape_tag_match(match: re.Match) -> str:
    """转义被拒绝标签的尖括号，使其作为普通文本显示。"""
    return match.group(0).replace("<", "&lt;").replace(">", "&gt;")


def _neutralize_boundary_tokens(text: str) -> str:
    """将正文中伪造或冲突的输入边界标记替换为无结构含义的文本。"""
    return _BOUNDARY_TOKEN_RE.sub(
        lambda m: _NEUTRALIZED_BEGIN if m.group(0) == _USER_INPUT_BEGIN else _NEUTRALIZED_END,
        text,
    )


def neutralize_untrusted_tags(text: str) -> str:
    """中和不可信文本中的框架标签和输入边界标记，但不添加用户消息专用的包裹标记。"""
    if not text.strip():
        return text
    text = _BLOCKED_TAG_PATTERN.sub(_escape_tag_match, text)
    return _neutralize_boundary_tokens(text)


def _is_genuine_user_message(message: object) -> bool:
    """识别真实用户消息，排除摘要和不含有效人工输入结果的隐藏消息。"""
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui") and read_human_input_response(message.additional_kwargs) is None:
        return False
    return True


def _check_user_content(text: str) -> str:
    """转义保留标签并包裹用户文本，同时保证重复处理不会嵌套边界标记。"""
    if not text.strip():
        return text
    text = _BLOCKED_TAG_PATTERN.sub(_escape_tag_match, text)
    # 只有文本完整包含首尾标记时才视为已处理，单独出现起始标记不算。
    if text.startswith(_USER_INPUT_BEGIN) and text.endswith(_USER_INPUT_END):
        # 即使已有外层标记也要处理中间正文，防止用户伪造包裹并插入内部边界。
        inner = text[len(_USER_INPUT_BEGIN) : -len(_USER_INPUT_END)]
        neutralized_inner = _neutralize_boundary_tokens(inner)
        if neutralized_inner == inner:
            return text
        return f"{_USER_INPUT_BEGIN}{neutralized_inner}{_USER_INPUT_END}"
    # 先中和用户自带的标记，防止跳过包裹或提前关闭输入边界。
    text = _neutralize_boundary_tokens(text)
    return f"{_USER_INPUT_BEGIN}\n{text}\n{_USER_INPUT_END}"


class InputSanitizationMiddleware(AgentMiddleware[AgentState]):
    """仅在模型请求副本中净化用户输入，不改写持久化的线程消息。"""

    @staticmethod
    def _extract_text_from_content(content: str | list) -> tuple[str, list | None]:
        """从字符串或多模态内容块中提取文本，并返回对应的原文本块引用。"""
        if isinstance(content, str):
            return content, None
        if not isinstance(content, list):
            return "", None
        text_parts: list[str] = []
        text_blocks: list[dict] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
                text_blocks.append(block)
        return "\n".join(text_parts), text_blocks

    @staticmethod
    def _rebuild_content(
        original_content: list,
        processed_text: str,
        text_blocks: list[dict],
    ) -> list:
        """将文本块合并为净化后的单块，同时保留夹在其中的图片等非文本块。"""
        text_block_ids = {id(b) for b in text_blocks}
        first = last = None
        for i, block in enumerate(original_content):
            if id(block) in text_block_ids:
                if first is None:
                    first = i
                last = i
        if first is None:
            return original_content
        result: list = [*original_content[:first], {"type": "text", "text": processed_text}]
        # 将首尾文本块之间的图片等非文本块按原顺序放回结果。
        for i in range(first + 1, last + 1):
            if id(original_content[i]) not in text_block_ids:
                result.append(original_content[i])
        result.extend(original_content[last + 1 :])
        return result

    def _process_request(self, request: ModelRequest) -> ModelRequest:
        """复制模型请求并净化最近一条真实用户消息，原状态和消息对象保持不变。"""
        messages = list(request.messages)
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if not _is_genuine_user_message(msg):
                if isinstance(msg, HumanMessage):
                    logger.debug(
                        "_process_request: skipping non-genuine HumanMessage at pos=%d name=%s hide_from_ui=%s content_preview=%.80r",
                        i,
                        msg.name,
                        msg.additional_kwargs.get("hide_from_ui"),
                        msg.content,
                    )
                continue
            content = msg.content
            logger.debug("_process_request: found genuine user message at pos=%d content=%.120r", i, content)

            text_content, text_blocks = self._extract_text_from_content(content)

            # 纯图片等没有文本的消息不做改写。
            if not text_content and not isinstance(content, str):
                logger.debug("_process_request: no text content in message — passing through")
                return request

            processed = _check_user_content(text_content)

            if processed == text_content:
                # 文本已经按规则处理，无需创建新请求。
                return request

            if text_blocks:
                new_content = self._rebuild_content(content, processed, text_blocks)
            else:
                new_content = processed

            # 保存净化前文本，供斜杠技能识别和重新生成等逻辑读取；保留合法上游值，
            # 并修复无效元数据，避免持久化时误用模型看到的包裹文本。
            preserved_kwargs = dict(msg.additional_kwargs or {})
            original_user_content = preserved_kwargs.get(ORIGINAL_USER_CONTENT_KEY)
            if not isinstance(original_user_content, str):
                if ORIGINAL_USER_CONTENT_KEY in preserved_kwargs:
                    logger.warning(
                        "InputSanitizationMiddleware replaced non-string %s metadata: type=%s",
                        ORIGINAL_USER_CONTENT_KEY,
                        type(original_user_content).__name__,
                    )
                preserved_kwargs[ORIGINAL_USER_CONTENT_KEY] = message_content_to_text(content)
            messages[i] = HumanMessage(
                content=new_content,
                id=msg.id,
                name=msg.name,
                additional_kwargs=preserved_kwargs,
            )
            logger.debug(
                "InputSanitizationMiddleware: original=%r -> processed=%r",
                content if isinstance(content, str) else "[content-blocks]",
                processed,
            )
            return request.override(messages=messages)
        return request

    def _try_process(self, request: ModelRequest) -> ModelRequest:
        """净化模型请求；图控制异常继续传播，其他内部错误则记录并放行原请求。"""
        try:
            return self._process_request(request)
        except GraphBubbleUp:
            raise
        except Exception:
            logger.warning(
                "用户输入净化失败，继续使用原请求调用模型",
                exc_info=True,
            )
            return request

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """清洗同步模型请求中的用户输入后执行后续处理器。"""
        return handler(self._try_process(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """清洗异步模型请求中的用户输入后等待后续处理器执行。"""
        return await handler(self._try_process(request))
