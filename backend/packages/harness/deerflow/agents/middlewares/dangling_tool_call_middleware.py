'''在模型调用前修正消息历史中的未完成工具调用、孤立结果及无法序列化的工具参数。'''

import json
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

_MAX_RECOVERY_ERROR_DETAIL_LEN = 500
_UNKNOWN_TOOL_NAME = "unknown_tool"
_EMPTY_TOOL_NAME_ERROR = "Tool call could not be executed because its name was missing or empty."


def _valid_tool_name(name: object) -> bool:
    '''判断工具名称是否为非空白字符串。'''
    return isinstance(name, str) and bool(name.strip())


def _normalize_tool_name(name: object) -> str:
    '''返回去除首尾空白的有效名称，或统一的未知工具名称。'''
    return name.strip() if _valid_tool_name(name) else _UNKNOWN_TOOL_NAME


def _has_invalid_tool_name(name: object) -> bool:
    '''判断工具名称是否无效。'''
    return not _valid_tool_name(name)


def _parse_json_object(value: object) -> dict | None:
    '''将字符串解析为 JSON 对象；输入不是对象或解析失败时返回 ``None``。'''
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_tool_arguments(arguments: object) -> str:
    '''将工具参数规范为可回放的 JSON 对象字符串，无法安全序列化时使用空对象。'''
    if isinstance(arguments, dict):
        try:
            return json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return "{}"
    return arguments if _parse_json_object(arguments) is not None else "{}"


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    '''修复消息历史中未配对的工具调用，并删除找不到原调用的孤立工具结果。'''

    @staticmethod
    def _message_tool_calls(msg) -> list[dict]:
        '''合并消息结构字段和供应商原始载荷中的工具调用，并规范工具名称供配对检查。'''
        normalized: list[dict] = []

        tool_calls = getattr(msg, "tool_calls", None) or []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                logger.debug("Skipping malformed non-dict tool_call in AIMessage: %r", tool_call)
                continue
            original_name = tool_call.get("name")
            normalized_call = dict(tool_call)
            normalized_call["name"] = _normalize_tool_name(original_name)
            if _has_invalid_tool_name(original_name):
                normalized_call["invalid_tool_name"] = True
            normalized.append(normalized_call)

        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        if not tool_calls:
            for raw_tc in raw_tool_calls:
                if not isinstance(raw_tc, dict):
                    continue

                function = raw_tc.get("function")
                name = raw_tc.get("name")
                if not name and isinstance(function, dict):
                    name = function.get("name")

                args = raw_tc.get("args", {})
                if not args and isinstance(function, dict):
                    parsed_args = _parse_json_object(function.get("arguments"))
                    args = parsed_args if parsed_args is not None else {}

                normalized_call = {
                    "id": raw_tc.get("id"),
                    "name": _normalize_tool_name(name),
                    "args": args if isinstance(args, dict) else {},
                }
                if _has_invalid_tool_name(name):
                    normalized_call["invalid_tool_name"] = True
                normalized.append(normalized_call)

        for invalid_tc in getattr(msg, "invalid_tool_calls", None) or []:
            if not isinstance(invalid_tc, dict):
                continue
            original_name = invalid_tc.get("name")
            normalized_call = {
                "id": invalid_tc.get("id"),
                "name": _normalize_tool_name(original_name),
                "args": {},
                "invalid": True,
                "error": invalid_tc.get("error"),
            }
            if _has_invalid_tool_name(original_name):
                normalized_call["invalid_tool_name"] = True
            normalized.append(normalized_call)

        return normalized

    @staticmethod
    def _synthetic_tool_message_content(tool_call: dict) -> str:
        '''为未执行的工具调用构造简短且可恢复的合成错误内容。'''
        if tool_call.get("invalid_tool_name"):
            return f"[{_EMPTY_TOOL_NAME_ERROR} Use one of the available tool names when retrying.]"
        if tool_call.get("invalid"):
            name = tool_call.get("name")
            error = tool_call.get("error")
            error_text = error[:_MAX_RECOVERY_ERROR_DETAIL_LEN] if isinstance(error, str) and error else ""
            if name == "write_file":
                details = f" Parser error: {error_text}" if error_text else ""
                return (
                    "[write_file failed before execution: the tool-call arguments were not valid JSON, "
                    "so no file was written. This often happens when the model tries to write a very "
                    "large Markdown file in a single tool call, especially when `content` contains "
                    "unescaped quotes, inline JSON, backslashes, or code fences. Do not retry the same "
                    "large `write_file` payload for this artifact; provide the report/content directly "
                    "as normal assistant text in your next response. If a file write is still needed "
                    f"later, split the file into smaller sections instead of one large payload.{details}]"
                )
            if error_text:
                return f"[Tool call could not be executed because its arguments were invalid: {error_text}]"
            return "[Tool call could not be executed because its arguments were invalid.]"
        return "[Tool call was interrupted and did not return a result.]"

    @staticmethod
    def _sanitize_ai_message_tool_calls(msg):
        '''规范模型消息中的工具名称和参数格式；没有变化时复用原消息。'''
        if getattr(msg, "type", None) != "ai":
            return msg

        changed = False
        update: dict = {}

        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            structured_changed = False
            sanitized_tool_calls = []
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    sanitized_tool_calls.append(tool_call)
                    continue
                name = tool_call.get("name")
                sanitized = dict(tool_call)
                normalized_name = _normalize_tool_name(name)
                if sanitized.get("name") != normalized_name:
                    sanitized["name"] = normalized_name
                    structured_changed = True
                sanitized_tool_calls.append(sanitized)
            if structured_changed:
                update["tool_calls"] = sanitized_tool_calls
                changed = True

        invalid_tool_calls = getattr(msg, "invalid_tool_calls", None)
        if invalid_tool_calls:
            invalid_changed = False
            sanitized_invalid_tool_calls = []
            for invalid_tool_call in invalid_tool_calls:
                if not isinstance(invalid_tool_call, dict):
                    sanitized_invalid_tool_calls.append(invalid_tool_call)
                    continue
                sanitized = dict(invalid_tool_call)
                normalized_name = _normalize_tool_name(sanitized.get("name"))
                normalized_arguments = _normalize_tool_arguments(sanitized.get("args"))
                if sanitized.get("name") != normalized_name:
                    sanitized["name"] = normalized_name
                    invalid_changed = True
                if sanitized.get("args") != normalized_arguments:
                    sanitized["args"] = normalized_arguments
                    invalid_changed = True
                sanitized_invalid_tool_calls.append(sanitized)
            if invalid_changed:
                update["invalid_tool_calls"] = sanitized_invalid_tool_calls
                changed = True

        additional_kwargs = dict(getattr(msg, "additional_kwargs", {}) or {})
        raw_tool_calls = additional_kwargs.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            raw_changed = False
            sanitized_raw_tool_calls = []
            for raw_tool_call in raw_tool_calls:
                if not isinstance(raw_tool_call, dict):
                    sanitized_raw_tool_calls.append(raw_tool_call)
                    continue

                sanitized_raw = dict(raw_tool_call)
                function = sanitized_raw.get("function")
                if isinstance(function, dict):
                    sanitized_function = dict(function)
                    normalized_name = _normalize_tool_name(sanitized_function.get("name"))
                    normalized_arguments = _normalize_tool_arguments(sanitized_function.get("arguments"))
                    if sanitized_function.get("name") != normalized_name:
                        sanitized_function["name"] = normalized_name
                        raw_changed = True
                    if sanitized_function.get("arguments") != normalized_arguments:
                        sanitized_function["arguments"] = normalized_arguments
                        raw_changed = True
                    if sanitized_function != function:
                        sanitized_raw["function"] = sanitized_function
                else:
                    normalized_name = _normalize_tool_name(sanitized_raw.get("name"))
                    if sanitized_raw.get("name") != normalized_name:
                        sanitized_raw["name"] = normalized_name
                        raw_changed = True
                sanitized_raw_tool_calls.append(sanitized_raw)

            if raw_changed:
                additional_kwargs["tool_calls"] = sanitized_raw_tool_calls
                update["additional_kwargs"] = additional_kwargs
                changed = True

        if not changed:
            return msg
        return msg.model_copy(update=update)

    def _build_patched_messages(self, messages: list) -> list | None:
        '''按工具调用顺序配对工具结果，为缺失结果补充错误消息，并移除失去原调用的孤立结果。'''
        tool_messages_by_id: dict[str, deque[ToolMessage]] = defaultdict(deque)
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_messages_by_id[msg.tool_call_id].append(msg)

        tool_call_ids: set[str] = set()
        for msg in messages:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if tc_id:
                    tool_call_ids.add(tc_id)

        patched: list = []
        patch_count = 0
        drop_count = 0
        for msg in messages:
            if isinstance(msg, ToolMessage):
                if msg.tool_call_id in tool_call_ids:
                    continue
                drop_count += 1
                continue

            sanitized_msg = self._sanitize_ai_message_tool_calls(msg)
            patched.append(sanitized_msg)
            if getattr(msg, "type", None) != "ai":
                continue

            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if not tc_id:
                    continue

                tool_msg_queue = tool_messages_by_id.get(tc_id)
                existing_tool_msg = tool_msg_queue.popleft() if tool_msg_queue else None
                if existing_tool_msg is not None:
                    if tc.get("invalid_tool_name") and _has_invalid_tool_name(existing_tool_msg.name):
                        existing_tool_msg = existing_tool_msg.model_copy(update={"name": tc["name"]})
                    patched.append(existing_tool_msg)
                else:
                    patched.append(
                        ToolMessage(
                            content=self._synthetic_tool_message_content(tc),
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    patch_count += 1

        if patched == messages and not drop_count:
            return None
        if drop_count or patch_count:
            logger.warning(
                "DanglingToolCallMiddleware: %d orphan(s) dropped, %d placeholder(s) injected",
                drop_count,
                patch_count,
            )
        return patched

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        '''在同步模型调用前修补工具消息顺序并交由后续处理器执行。'''
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        '''在异步模型调用前修补工具消息顺序并等待后续处理器执行。'''
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
