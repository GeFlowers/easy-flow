'''统一处理工具异常结果，并组装主代理与子代理共用的运行时中间件链。'''

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.skill_context import (
    SKILL_CONTEXT_ENTRY_KEY,
    _tool_call_path,
    build_skill_entry_metadata_from_read,
)
from deerflow.agents.middlewares.tool_result_meta import (
    normalize_tool_result,
    stamp_exception_meta,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.summarization_config import DEFAULT_SKILL_FILE_READ_TOOL_NAMES
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.subagents.status_contract import (
    format_subagent_result_message,
    make_subagent_additional_kwargs,
)

if TYPE_CHECKING:
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

logger = logging.getLogger(__name__)

_MISSING_TOOL_CALL_ID = "missing_tool_call_id"
_TASK_TOOL_NAME = "task"
_RECOVERY_HINT = "Continue with available context, or choose an alternative tool."


def _stamp_task_exception_status(message: ToolMessage, *, tool_name: str, error: str) -> ToolMessage:
    '''将任务工具异常包装为标准失败状态及结构化元数据，便于上层识别子代理失败。'''
    if tool_name != _TASK_TOOL_NAME:
        return message
    content, metadata_error = format_subagent_result_message("failed", error=error)
    if not content.endswith((".", "!", "?")):
        content += "."
    message.content = f"{content} {_RECOVERY_HINT}"
    existing = dict(message.additional_kwargs or {})
    existing.update(make_subagent_additional_kwargs("failed", error=metadata_error))
    message.additional_kwargs = existing
    return message


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    '''把工具执行异常转换为可恢复的错误消息，并补充技能读取及工具结果元数据。'''

    def __init__(self, *, app_config: AppConfig | None = None) -> None:
        '''保存应用配置，并确定用于识别技能文件读取工具的名称和技能根目录。'''
        super().__init__()
        self._app_config = app_config
        if app_config is None:
            self._skill_read_tool_names = frozenset(DEFAULT_SKILL_FILE_READ_TOOL_NAMES)
            self._skills_root = DEFAULT_SKILLS_CONTAINER_PATH
        else:
            self._skill_read_tool_names = frozenset(app_config.summarization.skill_file_read_tool_names)
            self._skills_root = app_config.skills.container_path

    def _build_error_message(self, request: ToolCallRequest, exc: Exception) -> ToolMessage:
        '''截断异常详情并构造工具错误消息；任务工具还会附带子代理失败状态。'''
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or _MISSING_TOOL_CALL_ID)
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."

        content = f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. {_RECOVERY_HINT}"
        message = ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )
        structured_error = f"{exc.__class__.__name__}: {detail}"
        message = _stamp_task_exception_status(message, tool_name=tool_name, error=structured_error)
        return stamp_exception_meta(message, structured_error)

    def _stamp_skill_read_metadata(
        self,
        message: ToolMessage,
        request: ToolCallRequest,
        *,
        tool_name: str,
    ) -> ToolMessage:
        '''为成功的技能文件读取结果附加技能条目元数据，供后续上下文恢复使用。'''
        if tool_name not in self._skill_read_tool_names:
            return message
        if getattr(message, "status", "success") == "error":
            return message
        content = message.content if isinstance(message.content, str) else None
        if content is None:
            return message
        path = _tool_call_path(request.tool_call)
        if path is None:
            return message
        entry = build_skill_entry_metadata_from_read(path, content, skills_root=self._skills_root)
        if entry is None:
            return message
        existing = dict(message.additional_kwargs or {})
        existing[SKILL_CONTEXT_ENTRY_KEY] = dict(entry)
        message.additional_kwargs = existing
        return message

    def _maybe_stamp(self, result: ToolMessage | Command, request: ToolCallRequest) -> ToolMessage | Command:
        '''仅对工具消息应用与当前工具类型对应的补充元数据；控制流结果保持原样。'''
        if not isinstance(result, ToolMessage):
            return result
        tool_name = str(request.tool_call.get("name") or "")
        return self._stamp_skill_read_metadata(result, request, tool_name=tool_name)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        '''同步执行工具调用，将普通异常转换为错误消息，同时原样传播图控制信号。'''
        try:
            result = handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (sync): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)
        return normalize_tool_result(self._maybe_stamp(result, request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        '''异步执行工具调用并采用与同步路径一致的异常转换和结果规范化规则。'''
        try:
            result = await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (async): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)
        return normalize_tool_result(self._maybe_stamp(result, request))


def _build_runtime_middlewares(
    *,
    app_config: AppConfig,
    include_uploads: bool,
    include_dangling_tool_call_patch: bool,
    lazy_init: bool = True,
) -> list[AgentMiddleware]:
    '''按执行阶段和配置组装输入防护、线程数据、沙箱、错误处理及可选功能中间件。'''
    from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
    from deerflow.agents.middlewares.tool_result_sanitization_middleware import ToolResultSanitizationMiddleware
    from deerflow.sandbox.middleware import SandboxMiddleware

    outer_wrappers: list[AgentMiddleware] = [
        InputSanitizationMiddleware(),
        ToolOutputBudgetMiddleware.from_app_config(app_config),
        ToolResultSanitizationMiddleware(),
    ]

    thread_hooks: list[AgentMiddleware] = [
        ThreadDataMiddleware(lazy_init=lazy_init),
    ]
    if include_uploads:
        from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware

        thread_hooks.append(UploadsMiddleware())
    thread_hooks.append(SandboxMiddleware(lazy_init=lazy_init))

    tail: list[AgentMiddleware] = []
    if include_dangling_tool_call_patch:
        from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

        tail.append(DanglingToolCallMiddleware())
    tail.append(LLMErrorHandlingMiddleware(app_config=app_config))

    guardrails_config = app_config.guardrails
    if guardrails_config.enabled and guardrails_config.provider:
        import inspect

        from deerflow.guardrails.middleware import GuardrailMiddleware
        from deerflow.reflection import resolve_variable

        provider_cls = resolve_variable(guardrails_config.provider.use)
        provider_kwargs = dict(guardrails_config.provider.config) if guardrails_config.provider.config else {}
        if "framework" not in provider_kwargs:
            try:
                sig = inspect.signature(provider_cls.__init__)
                if "framework" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    provider_kwargs["framework"] = "deerflow"
            except (ValueError, TypeError):
                pass
        provider = provider_cls(**provider_kwargs)
        tail.append(GuardrailMiddleware(provider, fail_closed=guardrails_config.fail_closed, passport=guardrails_config.passport))

    from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware

    tail.append(SandboxAuditMiddleware())

    if app_config.read_before_write.enabled:
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

        tail.append(ReadBeforeWriteMiddleware())

    tool_progress_config = app_config.tool_progress
    _ToolProgressMiddleware = None
    if tool_progress_config.enabled:
        from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware as _ToolProgressMiddleware

        tail.append(_ToolProgressMiddleware.from_config(tool_progress_config))

    tail.append(ToolErrorHandlingMiddleware(app_config=app_config))

    middlewares = [*outer_wrappers, *thread_hooks, *tail]

    if _ToolProgressMiddleware is not None:
        _progress_idx = next((i for i, m in enumerate(middlewares) if isinstance(m, _ToolProgressMiddleware)), None)
        _error_idx = next((i for i, m in enumerate(middlewares) if isinstance(m, ToolErrorHandlingMiddleware)), None)
        if _progress_idx is not None and _error_idx is not None and _progress_idx > _error_idx:
            raise RuntimeError(f"ToolProgressMiddleware must be outer (index {_progress_idx}) of ToolErrorHandlingMiddleware (index {_error_idx}) — check middleware append order")

    return middlewares


def build_lead_runtime_middlewares(*, app_config: AppConfig, lazy_init: bool = True) -> list[AgentMiddleware]:
    '''构造主代理共用中间件链，并启用上传文件处理和悬空工具调用修复。'''
    return _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=True,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )


def build_subagent_runtime_middlewares(
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    lazy_init: bool = True,
    deferred_setup: "DeferredToolSetup | None" = None,
    mcp_routing_middleware: AgentMiddleware | None = None,
    agent_name: str | None = None,
) -> list[AgentMiddleware]:
    '''为子代理组装共用中间件，并依据模型能力、工具路由和应用开关附加运行保护。'''
    if app_config is None:
        from deerflow.config import get_app_config

        app_config = get_app_config()

    middlewares = _build_runtime_middlewares(
        app_config=app_config,
        include_uploads=False,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )

    if model_name is None and app_config.models:
        model_name = app_config.models[0].name

    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

        middlewares.append(ViewImageMiddleware())

    if mcp_routing_middleware is not None:
        middlewares.append(mcp_routing_middleware)

    if deferred_setup is not None and deferred_setup.deferred_names:
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        middlewares.append(DeferredToolFilterMiddleware(deferred_setup.deferred_names, deferred_setup.catalog_hash))
        from deerflow.agents.middlewares.mcp_routing_middleware import assert_mcp_routing_before_deferred_filter

        assert_mcp_routing_before_deferred_filter(middlewares)

    loop_detection_config = app_config.loop_detection
    if loop_detection_config.enabled:
        from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

        middlewares.append(LoopDetectionMiddleware.from_config(loop_detection_config))

    summarization_enabled = app_config.summarization.enabled
    if agent_name is not None:
        token_budget_config = app_config.subagents.get_token_budget_for(agent_name, summarization_enabled=summarization_enabled)
    else:
        token_budget_config = app_config.subagents.token_budget
    if token_budget_config.enabled:
        from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware

        middlewares.append(TokenBudgetMiddleware.from_config(token_budget_config))

    safety_config = app_config.safety_finish_reason
    if safety_config.enabled:
        from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

        middlewares.append(SafetyFinishReasonMiddleware.from_config(safety_config))

    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

    middlewares.append(
        DurableContextMiddleware(
            skills_container_path=app_config.skills.container_path,
            skill_file_read_tool_names=app_config.summarization.skill_file_read_tool_names,
        )
    )

    from deerflow.agents.middlewares.summarization_middleware import create_summarization_middleware

    summarization_middleware = create_summarization_middleware(
        app_config=app_config,
        skip_memory_flush=True,
    )
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware

    middlewares.append(SystemMessageCoalescingMiddleware())

    return middlewares
