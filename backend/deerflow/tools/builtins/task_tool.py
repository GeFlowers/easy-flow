'''提供将任务委派给子代理的工具。'''

import asyncio
import logging
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated, Any, cast

from langchain.tools import InjectedToolCallId, tool
from langchain_core.callbacks import BaseCallbackManager
from langchain_core.messages import ToolMessage
from langgraph.config import get_stream_writer
from langgraph.types import Command

from deerflow.config import get_app_config
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.security import LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE, is_host_bash_allowed
from deerflow.subagents import SubagentExecutor, get_available_subagent_names, get_subagent_config
from deerflow.subagents.config import resolve_subagent_model_name
from deerflow.subagents.executor import (
    SubagentStatus,
    cleanup_background_task,
    get_background_task_result,
    request_cancel_background_task,
)
from deerflow.subagents.status_contract import (
    SubagentStatusValue,
    SubagentStopReasonValue,
    format_subagent_result_message,
    make_subagent_additional_kwargs,
)
from deerflow.tools.types import Runtime
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, normalize_trace_id

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_subagent_usage_cache: dict[str, dict[str, int]] = {}


def _token_usage_cache_enabled(app_config: "AppConfig | None") -> bool:
    '''判断是否启用子代理令牌用量缓存。'''
    if app_config is None:
        try:
            app_config = get_app_config()
        except FileNotFoundError:
            return False
    return bool(getattr(getattr(app_config, "token_usage", None), "enabled", False))


def _cache_subagent_usage(tool_call_id: str, usage: dict | None, *, enabled: bool = True) -> None:
    '''在启用时按工具调用标识缓存子代理用量。'''
    if enabled and usage:
        _subagent_usage_cache[tool_call_id] = usage


def pop_cached_subagent_usage(tool_call_id: str) -> dict | None:
    '''取出并删除指定工具调用的缓存用量。'''
    return _subagent_usage_cache.pop(tool_call_id, None)


def _is_subagent_terminal(result: Any) -> bool:
    '''判断后台子代理结果是否已终止且可以安全清理。'''
    return result.status in {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.CANCELLED, SubagentStatus.TIMED_OUT} or getattr(result, "completed_at", None) is not None


async def _await_subagent_terminal(task_id: str, max_polls: int) -> Any | None:
    '''轮询后台子代理，直至其终止或耗尽允许的轮询次数。'''
    for _ in range(max_polls):
        result = get_background_task_result(task_id)
        if result is None:
            return None
        if _is_subagent_terminal(result):
            return result
        await asyncio.sleep(5)
    return None


async def _deferred_cleanup_subagent_task(task_id: str, trace_id: str, max_polls: int) -> None:
    '''持续轮询已取消的子代理，直至可以安全移除。'''
    cleanup_poll_count = 0
    while True:
        result = get_background_task_result(task_id)
        if result is None:
            return
        if _is_subagent_terminal(result):
            cleanup_background_task(task_id)
            return
        if cleanup_poll_count >= max_polls:
            logger.warning(f"[trace={trace_id}] Deferred cleanup for task {task_id} timed out after {cleanup_poll_count} polls")
            return
        await asyncio.sleep(5)
        cleanup_poll_count += 1


def _log_cleanup_failure(cleanup_task: asyncio.Task[None], *, trace_id: str, task_id: str) -> None:
    '''记录延后清理任务执行失败的异常。'''
    if cleanup_task.cancelled():
        return

    exc = cleanup_task.exception()
    if exc is not None:
        logger.error(f"[trace={trace_id}] Deferred cleanup failed for task {task_id}: {exc}")


def _schedule_deferred_subagent_cleanup(task_id: str, trace_id: str, max_polls: int) -> None:
    '''为已取消的子代理安排延后清理任务。'''
    logger.debug(f"[trace={trace_id}] Scheduling deferred cleanup for cancelled task {task_id}")
    cleanup_task = asyncio.create_task(_deferred_cleanup_subagent_task(task_id, trace_id, max_polls))
    cleanup_task.add_done_callback(lambda task: _log_cleanup_failure(task, trace_id=trace_id, task_id=task_id))


def _find_usage_recorder(runtime: Any) -> Any | None:
    '''从运行时配置中查找实现 ``record_external_llm_usage_records`` 的回调处理器。

    LangChain 传入的 ``config["callbacks"]`` 可能有三种形式：
    - ``None``：未注册回调，不存在记录器。
    - 普通 ``list[BaseCallbackHandler]``：可直接迭代。
    - ``BaseCallbackManager`` 实例：例如异步工具运行时的 ``AsyncCallbackManager``，
      管理器不可迭代，须先取出 ``.handlers``。

    其他形式（例如未包装为列表的单个处理器）无法安全迭代，按无记录器处理，
    而不抛出异常。
    '''
    if runtime is None:
        return None
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        return None
    callbacks = config.get("callbacks")
    if isinstance(callbacks, BaseCallbackManager):
        callbacks = callbacks.handlers
    if not callbacks:
        return None
    if not isinstance(callbacks, list):
        return None
    for cb in callbacks:
        if hasattr(cb, "record_external_llm_usage_records"):
            return cb
    return None


def _summarize_usage(records: list[dict] | None) -> dict | None:
    '''将令牌用量记录汇总为适用于 SSE 事件的紧凑字典。'''
    if not records:
        return None
    return {
        "input_tokens": sum(r.get("input_tokens", 0) or 0 for r in records),
        "output_tokens": sum(r.get("output_tokens", 0) or 0 for r in records),
        "total_tokens": sum(r.get("total_tokens", 0) or 0 for r in records),
    }


def _report_subagent_usage(runtime: Any, result: Any) -> None:
    '''在可用时向父级运行日志报告子代理的令牌用量。

    每个子代理任务只报告一次，由 usage_reported 标记保护。
    '''
    if getattr(result, "usage_reported", True):
        return
    records = getattr(result, "token_usage_records", None) or []
    if not records:
        return
    journal = _find_usage_recorder(runtime)
    if journal is None:
        logger.debug("No usage recorder found in runtime callbacks — subagent token usage not recorded")
        return
    try:
        journal.record_external_llm_usage_records(records)
        result.usage_reported = True
    except Exception:
        logger.warning("Failed to report subagent token usage", exc_info=True)


def _get_runtime_app_config(runtime: Any) -> "AppConfig | None":
    '''从运行时上下文取得应用配置。'''
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        app_config = context.get("app_config")
        if app_config is not None:
            return cast("AppConfig", app_config)
    return None


def _merge_skill_allowlists(parent: list[str] | None, child: list[str] | None) -> list[str] | None:
    '''在父级策略约束下返回有效的子代理技能白名单。'''
    if parent is None:
        return child
    if child is None:
        return list(parent)

    parent_set = set(parent)
    return [skill for skill in child if skill in parent_set]


def _task_result_command(
    *,
    tool_call_id: str,
    status: SubagentStatusValue,
    result: str | None = None,
    error: str | None = None,
    stop_reason: SubagentStopReasonValue | None = None,
    model_name: str | None = None,
    usage: dict[str, int] | None = None,
) -> Command:
    '''构造携带子代理任务结果及其元数据的状态更新命令。'''
    content, metadata_error = format_subagent_result_message(status, result=result, error=error, stop_reason=stop_reason)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    name="task",
                    additional_kwargs=make_subagent_additional_kwargs(
                        status,
                        result=result,
                        error=metadata_error,
                        stop_reason=stop_reason,
                        model_name=model_name,
                        token_usage=usage,
                    ),
                )
            ]
        }
    )


@tool("task", parse_docstring=True)
async def task_tool(
    runtime: Runtime,
    description: str,
    prompt: str,
    subagent_type: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> str | Command:
    '''将任务委派给在独立上下文中运行的专用子代理。

    子代理有助于分开探索与实现以节省上下文、自主处理复杂的多步骤任务，
    以及在隔离上下文中执行命令或操作。

    内置子代理类型：
    - **general-purpose**：适合需要探索和行动的复杂任务，尤其是需要复杂推理、
      多个相互依赖步骤，或可受益于上下文隔离的任务。
    - **bash**：专门执行 bash 命令；仅在明确允许宿主机 bash，或采用启用宿主机
      bash 的隔离命令解释器可信本地沙箱配置时可用。

    可在 config.yaml 的 `subagents.custom_agents` 下定义自定义类型，每种类型
    可具有独立的系统提示词、工具、技能、模型和超时设置。传入未知的 subagent_type
    时，错误消息会列出可用类型。

    适用于需要多个步骤或工具的复杂任务、输出量较大的任务、需要与主对话隔离
    上下文的任务，以及并行研究或探索。简单单步操作应直接调用工具；需要用户
    交互或澄清的任务不适合委派。

    Args:
        description: 用于日志或界面展示的简短任务描述，约 3 至 5 个词。始终首先提供此参数。
        prompt: 给子代理的任务说明，应具体清楚地描述要完成的工作。始终第二个提供此参数。
        subagent_type: 要使用的子代理类型。始终第三个提供此参数。
    '''
    runtime_app_config = _get_runtime_app_config(runtime)
    cache_token_usage = _token_usage_cache_enabled(runtime_app_config)
    available_subagent_names = get_available_subagent_names(app_config=runtime_app_config) if runtime_app_config is not None else get_available_subagent_names()

    config = get_subagent_config(subagent_type, app_config=runtime_app_config) if runtime_app_config is not None else get_subagent_config(subagent_type)
    if config is None:
        available = ", ".join(available_subagent_names)
        error = f"Unknown subagent type '{subagent_type}'. Available: {available}"
        return _task_result_command(
            tool_call_id=tool_call_id,
            status="failed",
            error=error,
        )
    if subagent_type == "bash":
        host_bash_allowed = is_host_bash_allowed(runtime_app_config) if runtime_app_config is not None else is_host_bash_allowed()
        if not host_bash_allowed:
            return _task_result_command(
                tool_call_id=tool_call_id,
                status="failed",
                error=LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE,
            )

    overrides: dict = {}


    sandbox_state = None
    thread_data = None
    thread_id = None
    parent_model = None
    trace_id = None
    user_id = None
    deerflow_trace_id = None
    metadata: dict = {}

    if runtime is not None:
        sandbox_state = runtime.state.get("sandbox")
        thread_data = runtime.state.get("thread_data")
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id is None:
            thread_id = runtime.config.get("configurable", {}).get("thread_id")

        metadata = runtime.config.get("metadata", {})
        parent_model = metadata.get("model_name")

        trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]

    user_id = resolve_runtime_user_id(runtime)

    parent_context = runtime.context if runtime is not None else None
    parent_context = parent_context if isinstance(parent_context, dict) else {}
    user_role = parent_context.get("user_role")
    oauth_provider = parent_context.get("oauth_provider")
    oauth_id = parent_context.get("oauth_id")
    run_id = parent_context.get("run_id")
    channel_user_id = parent_context.get("channel_user_id")
    deerflow_trace_id = normalize_trace_id(parent_context.get(DEERFLOW_TRACE_METADATA_KEY)) or normalize_trace_id(metadata.get(DEERFLOW_TRACE_METADATA_KEY)) or get_current_trace_id()

    parent_available_skills = metadata.get("available_skills")
    if parent_available_skills is not None:
        overrides["skills"] = _merge_skill_allowlists(list(parent_available_skills), config.skills)

    if overrides:
        config = replace(config, **overrides)

    from deerflow.tools import get_available_tools

    parent_tool_groups = metadata.get("tool_groups")
    resolved_app_config = runtime_app_config
    if config.model == "inherit" and parent_model is None and resolved_app_config is None:
        resolved_app_config = get_app_config()
    effective_model = resolve_subagent_model_name(config, parent_model, app_config=resolved_app_config)

    available_tools_kwargs = {
        "model_name": effective_model,
        "groups": parent_tool_groups,
        "subagent_enabled": False,
    }
    if resolved_app_config is not None:
        available_tools_kwargs["app_config"] = resolved_app_config
    tools = get_available_tools(**available_tools_kwargs)

    executor_kwargs = {
        "config": config,
        "tools": tools,
        "parent_model": parent_model,
        "sandbox_state": sandbox_state,
        "thread_data": thread_data,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "user_id": user_id,
        "user_role": user_role,
        "oauth_provider": oauth_provider,
        "oauth_id": oauth_id,
        "run_id": run_id,
        "channel_user_id": channel_user_id,
        "deerflow_trace_id": deerflow_trace_id,
    }
    if resolved_app_config is not None:
        executor_kwargs["app_config"] = resolved_app_config
    executor = SubagentExecutor(**executor_kwargs)

    task_id = executor.execute_async(prompt, task_id=tool_call_id)

    poll_count = 0
    last_status = None
    last_message_count = 0
    max_poll_count = (config.timeout_seconds + 60) // 5

    logger.info(f"[trace={trace_id}] Started background task {task_id} (subagent={subagent_type}, timeout={config.timeout_seconds}s, polling_limit={max_poll_count} polls)")

    writer = get_stream_writer()
    writer(
        {
            "type": "task_started",
            "task_id": task_id,
            "description": description,
            "model_name": effective_model,
        }
    )

    try:
        while True:
            result = get_background_task_result(task_id)

            if result is None:
                logger.error(f"[trace={trace_id}] Task {task_id} not found in background tasks")
                writer({"type": "task_failed", "task_id": task_id, "error": "Task disappeared from background tasks"})
                cleanup_background_task(task_id)
                error = f"Task {task_id} disappeared from background tasks"
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="failed",
                    error=error,
                )

            if result.status != last_status:
                logger.info(f"[trace={trace_id}] Task {task_id} status: {result.status.value}")
                last_status = result.status

            usage = _summarize_usage(getattr(result, "token_usage_records", None))

            ai_messages = result.ai_messages or []
            current_message_count = len(ai_messages)
            if current_message_count > last_message_count:
                for i in range(last_message_count, current_message_count):
                    message = ai_messages[i]
                    writer(
                        {
                            "type": "task_running",
                            "task_id": task_id,
                            "message": message,
                            "message_index": i + 1,
                            "total_messages": current_message_count,
                            "usage": usage,
                            "model_name": effective_model,
                        }
                    )
                    logger.info(f"[trace={trace_id}] Task {task_id} sent message #{i + 1}/{current_message_count}")
                last_message_count = current_message_count

            if result.status == SubagentStatus.COMPLETED:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_completed",
                        "task_id": task_id,
                        "result": result.result,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.info(f"[trace={trace_id}] Task {task_id} completed after {poll_count} polls")
                cleanup_background_task(task_id)
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="completed",
                    result=result.result,
                    stop_reason=result.stop_reason,
                    model_name=effective_model,
                    usage=usage,
                )
            elif result.status == SubagentStatus.FAILED:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_failed",
                        "task_id": task_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.error(f"[trace={trace_id}] Task {task_id} failed: {result.error}")
                cleanup_background_task(task_id)
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="failed",
                    error=result.error,
                    stop_reason=result.stop_reason,
                    model_name=effective_model,
                    usage=usage,
                )
            elif result.status == SubagentStatus.CANCELLED:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_cancelled",
                        "task_id": task_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.info(f"[trace={trace_id}] Task {task_id} cancelled: {result.error}")
                cleanup_background_task(task_id)
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="cancelled",
                    error=result.error,
                    model_name=effective_model,
                    usage=usage,
                )
            elif result.status == SubagentStatus.TIMED_OUT:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_timed_out",
                        "task_id": task_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.warning(f"[trace={trace_id}] Task {task_id} timed out: {result.error}")
                cleanup_background_task(task_id)
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="timed_out",
                    error=result.error,
                    model_name=effective_model,
                    usage=usage,
                )

            await asyncio.sleep(5)
            poll_count += 1

            if poll_count > max_poll_count:
                timeout_minutes = config.timeout_seconds // 60
                logger.error(f"[trace={trace_id}] Task {task_id} polling timed out after {poll_count} polls (should have been caught by thread pool timeout)")
                _report_subagent_usage(runtime, result)
                usage = _summarize_usage(getattr(result, "token_usage_records", None))
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                writer(
                    {
                        "type": "task_timed_out",
                        "task_id": task_id,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                request_cancel_background_task(task_id)
                _schedule_deferred_subagent_cleanup(task_id, trace_id, max_poll_count)
                message = f"Task polling timed out after {timeout_minutes} minutes. This may indicate the background task is stuck. Status: {result.status.value}"
                return _task_result_command(
                    tool_call_id=tool_call_id,
                    status="polling_timed_out",
                    error=message,
                    model_name=effective_model,
                    usage=usage,
                )
    except asyncio.CancelledError:
        request_cancel_background_task(task_id)

        terminal_result = None
        try:
            terminal_result = await asyncio.shield(_await_subagent_terminal(task_id, max_poll_count))
        except asyncio.CancelledError:
            pass

        final_result = terminal_result or get_background_task_result(task_id)
        if final_result is not None:
            _report_subagent_usage(runtime, final_result)
        if final_result is not None and _is_subagent_terminal(final_result):
            cleanup_background_task(task_id)
        else:
            _schedule_deferred_subagent_cleanup(task_id, trace_id, max_poll_count)
        _subagent_usage_cache.pop(tool_call_id, None)
        raise
    except Exception:
        _subagent_usage_cache.pop(tool_call_id, None)
        raise
