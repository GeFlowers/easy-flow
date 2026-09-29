"""运行生命周期服务层。

集中处理运行创建、SSE 帧格式化及流桥事件消费；``thread_runs`` 和 ``runs`` 路由模块
仅作为委托至本模块的轻量 HTTP 处理器。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import convert_to_messages
from langgraph.types import Command

from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
from app.gateway.deps import get_checkpointer, get_local_provider, get_run_context, get_run_manager, get_stream_bridge
from app.gateway.internal_auth import (
    INTERNAL_OWNER_USER_ID_HEADER_NAME,
    INTERNAL_SYSTEM_ROLE,
    get_internal_user,
    get_trusted_internal_owner_user_id,
)
from app.gateway.utils import sanitize_log_param
from deerflow.agents.middlewares.dynamic_context_middleware import _DYNAMIC_CONTEXT_REMINDER_KEY, _REMINDER_DATE_KEY
from deerflow.config.app_config import get_app_config
from deerflow.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    ConflictError,
    DisconnectMode,
    RunManager,
    RunRecord,
    RunStatus,
    StreamBridge,
    UnsupportedStrategyError,
    run_agent,
)
from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.runs.naming import resolve_root_run_name
from deerflow.runtime.secret_context import redact_config_secrets
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = {
    RunStatus.success,
    RunStatus.error,
    RunStatus.timeout,
    RunStatus.interrupted,
}

_SERVER_OWNED_DYNAMIC_CONTEXT_KEYS = frozenset(
    {
        _DYNAMIC_CONTEXT_REMINDER_KEY,
        _REMINDER_DATE_KEY,
    }
)


# ---------------------------------------------------------------------------
# SSE 帧格式化。
# ---------------------------------------------------------------------------


def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """格式化单个 SSE 帧。

    字段顺序为 ``event:``、``data:``、可选 ``id:`` 与空行，匹配 useStream React Hook
    和 Python langgraph-sdk SSE 解码器使用的 LangGraph Platform 线协议。
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


def _run_is_terminal(record: RunRecord) -> bool:
    """判断运行记录是否已进入不会继续产生事件的终态。"""
    return record.status in _TERMINAL_RUN_STATUSES


async def _terminal_record_stream_missing(bridge: StreamBridge, record: RunRecord) -> bool:
    """支持查询的桥接器中，终态运行无保留事件流时返回 ``True``。"""
    if not _run_is_terminal(record):
        return False
    stream_exists = getattr(bridge, "stream_exists", None)
    if stream_exists is None:
        return False
    try:
        return not bool(await stream_exists(record.run_id))
    except Exception:
        logger.debug(
            "Failed to probe stream existence for terminal run %s",
            sanitize_log_param(record.run_id),
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# 输入与配置辅助函数。
# ---------------------------------------------------------------------------


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """将 stream_mode 参数规范化为列表，默认值匹配 useStream 所需的 values 与 messages-tuple。"""
    if raw is None:
        return ["values"]
    if isinstance(raw, str):
        return [raw]
    return raw if raw else ["values"]


def _strip_external_message_metadata(message: Any) -> Any:
    """移除不受信任输入消息中由服务端持有的元数据。"""
    if not isinstance(message, BaseMessage):
        return message
    additional_kwargs = dict(message.additional_kwargs)
    additional_kwargs.pop(ORIGINAL_USER_CONTENT_KEY, None)
    for key in _SERVER_OWNED_DYNAMIC_CONTEXT_KEYS:
        additional_kwargs.pop(key, None)
    if additional_kwargs == message.additional_kwargs:
        return message
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def normalize_input(raw_input: dict[str, Any] | None, *, trusted_internal: bool = False) -> dict[str, Any]:
    """将 LangGraph 输入转换为消息状态，保留合法元数据并拒绝外部伪造的服务端字段。"""
    if raw_input is None:
        return {}
    messages = raw_input.get("messages")
    if messages and isinstance(messages, list):
        converted: list[Any] = []
        for index, msg in enumerate(messages):
            if isinstance(msg, BaseMessage):
                converted.append(msg)
            elif isinstance(msg, dict):
                try:
                    converted.extend(convert_to_messages([msg]))
                except (ValueError, TypeError, NotImplementedError) as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid message at input.messages[{index}]: {exc}",
                    ) from exc
            else:
                converted.append(msg)
        if not trusted_internal:
            converted = [_strip_external_message_metadata(message) for message in converted]
        return {**raw_input, "messages": converted}
    return raw_input


_DEFAULT_ASSISTANT_ID = "lead_agent"


# Whitelist of run-context keys that the langgraph-compat layer forwards from
# ``body.context`` into the run config. ``config["context"]`` exists in
# LangGraph >=0.6, but these values must be written to both ``configurable``
# (for legacy ``_get_runtime_config`` consumers) and ``context`` because
# LangGraph >=1.1.9 no longer makes ``ToolRuntime.context`` fall back to
# ``configurable`` for consumers like ``setup_agent``.
_CONTEXT_CONFIGURABLE_KEYS: frozenset[str] = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "max_total_subagents",
        "agent_name",
        "is_bootstrap",
    }
)

# Keys honored only for internally-authenticated callers (the scheduler path).
# ``non_interactive`` strips ``ask_clarification`` from the lead-agent toolset;
# arbitrary HTTP/IM clients must not be able to force autonomous execution.
_CONTEXT_INTERNAL_CALLER_KEYS: frozenset[str] = frozenset({"non_interactive"})

# Keys forwarded from ``body.context`` into ``config['context']`` ONLY (the
# runtime context that becomes ``ToolRuntime.context`` / ``runtime.context``),
# never into ``config['configurable']``. These are read by tools and
# middlewares from ``runtime.context`` and have no reason to live in
# ``configurable`` — and ``configurable`` is persisted in checkpoints, so
# keeping secrets like ``github_token`` out of it avoids writing a
# short-lived installation token into the checkpoint store.
#
#   ``github_token``         — App installation token minted by the GitHub
#                              channel; the bash tool exposes it as
#                              ``GH_TOKEN``/``GITHUB_TOKEN`` so ``gh`` and
#                              ``git`` push as the bot, not the host user.
#   ``disable_clarification`` — set for non-interactive channels (GitHub
#                              webhooks) so ClarificationMiddleware proceeds
#                              instead of dead-ending the run.
_CONTEXT_RUNTIME_ONLY_KEYS: frozenset[str] = frozenset({"github_token", "disable_clarification"})


def strip_internal_context_keys(config: dict[str, Any]) -> None:
    """从已组装配置的 context 和 configurable 中移除仅限内部调用的字段。"""
    for section in ("context", "configurable"):
        value = config.get(section)
        if isinstance(value, dict):
            for key in _CONTEXT_INTERNAL_CALLER_KEYS:
                value.pop(key, None)


def merge_run_context_overrides(config: dict[str, Any], context: Mapping[str, Any] | None, *, internal: bool = False) -> None:
    """按调用方信任级别合并白名单上下文，并将密钥和运行标记限制在运行时 context。"""
    if not context:
        return
    configurable = config.setdefault("configurable", {})
    runtime_context = config.setdefault("context", {})
    keys = _CONTEXT_CONFIGURABLE_KEYS | _CONTEXT_INTERNAL_CALLER_KEYS if internal else _CONTEXT_CONFIGURABLE_KEYS
    for key in keys:
        if key in context:
            if isinstance(configurable, dict):
                configurable.setdefault(key, context[key])
            if isinstance(runtime_context, dict):
                runtime_context.setdefault(key, context[key])
    # Context-only keys (secrets / runtime flags) land in ``config['context']``
    # only — never ``configurable`` (which is persisted in checkpoints).
    for key in _CONTEXT_RUNTIME_ONLY_KEYS:
        if key in context and isinstance(runtime_context, dict):
            runtime_context.setdefault(key, context[key])
    if "user_id" in context and isinstance(runtime_context, dict):
        runtime_context.setdefault("user_id", context["user_id"])
    # The raw platform user id from IM channels (Feishu open_id, Slack Uxxx, ...)
    # follows the same runtime-context-only rule as user_id: tools may read it,
    # but it never enters ``configurable`` (checkpointed with the thread).
    if "channel_user_id" in context and isinstance(runtime_context, dict):
        runtime_context.setdefault("channel_user_id", context["channel_user_id"])


async def resolve_trusted_internal_owner_for_attribution(request: Request, owner_user_id: str | None) -> Any | None:
    """仅在可信内部请求中解析所有者用户，供运行归属信息记录使用。"""

    if not owner_user_id:
        return None
    user = getattr(request.state, "user", None)
    if getattr(user, "system_role", None) != INTERNAL_SYSTEM_ROLE:
        return None
    try:
        return await get_local_provider().get_user(owner_user_id)
    except Exception:
        logger.exception("Failed to resolve trusted internal owner %s", sanitize_log_param(owner_user_id))
        return None


def inject_authenticated_user_context(
    config: dict[str, Any],
    request: Request,
    *,
    internal_owner_user: Any | None = None,
) -> None:
    """将服务端认证得到的用户及身份属性写入运行时上下文，供后台工具使用。"""

    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        return

    if getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        runtime_context = config.setdefault("context", {})
        if not isinstance(runtime_context, dict):
            return
        if internal_owner_user is None:
            runtime_context.pop("user_role", None)
            runtime_context.pop("oauth_provider", None)
            runtime_context.pop("oauth_id", None)
            return
        owner_user_id = getattr(internal_owner_user, "id", None)
        if owner_user_id is not None:
            runtime_context["user_id"] = str(owner_user_id)
        runtime_context["user_role"] = getattr(internal_owner_user, "system_role", None)
        runtime_context["oauth_provider"] = getattr(internal_owner_user, "oauth_provider", None)
        runtime_context["oauth_id"] = getattr(internal_owner_user, "oauth_id", None)
        return

    runtime_context = config.setdefault("context", {})
    if isinstance(runtime_context, dict):
        runtime_context["user_id"] = str(user_id)
        runtime_context["user_role"] = getattr(user, "system_role", None)
        runtime_context["oauth_provider"] = getattr(user, "oauth_provider", None)
        runtime_context["oauth_id"] = getattr(user, "oauth_id", None)


def resolve_agent_factory(assistant_id: str | None):
    """返回统一的 lead-agent 工厂；具体 Agent 由运行配置中的 agent_name 选择。"""
    from deerflow.agents.lead_agent.agent import make_lead_agent

    return make_lead_agent


# Lead-agent recursion budget bounds. The Gateway must NOT trust a
# client-supplied ``recursion_limit`` verbatim: an arbitrarily large value lets
# a single run execute unbounded LangGraph super-steps (each at least one LLM
# call), enabling runaway API cost / DoS. ``_DEFAULT_RECURSION_LIMIT`` is the
# server default when the client sends nothing; the hard ceiling any client
# value is clamped to is configurable via ``AppConfig.max_recursion_limit``.
_DEFAULT_RECURSION_LIMIT = 100
_DEFAULT_MAX_RECURSION_LIMIT = 1000


def _resolve_max_recursion_limit() -> int:
    """读取服务端递归上限；配置不可用时使用内置上限继续保护运行。"""
    try:
        return get_app_config().max_recursion_limit
    except Exception:
        return _DEFAULT_MAX_RECURSION_LIMIT


def _clamp_recursion_limit(value: Any, max_limit: int) -> int:
    """校验客户端递归步数并限制在服务端上限内，无效值回退到默认值。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return _DEFAULT_RECURSION_LIMIT
    return min(value, max_limit)


def build_run_config(
    thread_id: str,
    request_config: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    assistant_id: str | None = None,
) -> dict[str, Any]:
    """组装 Agent 运行配置，注入线程与自定义 Agent 名称，并限制递归步数。"""
    # Lead-agent recursion budget (LangGraph super-steps for the lead graph
    # only). Independent of subagent depth: a `task()` dispatch runs the whole
    # subagent inside ONE lead tools-node step, and subagents enforce their own
    # limit via `subagents.max_turns`. Do not conflate this 100 with the
    # general-purpose subagent's max_turns.
    config: dict[str, Any] = {"recursion_limit": _DEFAULT_RECURSION_LIMIT}
    if request_config:
        # LangGraph >= 0.6.0 introduced ``context`` as the preferred way to
        # pass thread-level data and rejects requests that include both
        # ``configurable`` and ``context``.  If the caller already sends
        # ``context``, honour it and skip our own ``configurable`` dict.
        if "context" in request_config:
            if "configurable" in request_config:
                logger.warning(
                    "build_run_config: client sent both 'context' and 'configurable'; preferring 'context' (LangGraph >= 0.6.0). thread_id=%s, caller_configurable keys=%s",
                    thread_id,
                    list(request_config.get("configurable", {}).keys()),
                )
            context_value = request_config["context"]
            if context_value is None:
                context = {}
            elif isinstance(context_value, Mapping):
                # Strip caller-supplied ``__``-prefixed keys: those are the
                # harness's private run-context channels (skill secret-binding
                # sources, the active-secret set, the run journal). A caller must
                # not be able to seed them and forge internal state — e.g. a
                # forged ``__slash_skill_secret_source`` would otherwise bypass the
                # skill enabled/allowlist/declaration gates (#3938). Legitimate
                # caller keys (``secrets``, ``user_id``, model overrides) never use
                # the ``__`` prefix.
                context = {key: value for key, value in context_value.items() if not (isinstance(key, str) and key.startswith("__"))}
            else:
                raise ValueError("request config 'context' must be a mapping or null.")
            context["thread_id"] = thread_id
            config["context"] = context
            # The checkpointer always scopes state by configurable["thread_id"],
            # regardless of whether the caller drives the run via context (e.g.
            # request-scoped secrets, #3861). thread_id comes from the URL path,
            # not caller config, so mirror it here while keeping secret-bearing
            # context keys out of configurable.
            config["configurable"] = {"thread_id": thread_id}
        else:
            configurable = {"thread_id": thread_id}
            configurable.update(request_config.get("configurable", {}))
            config["configurable"] = configurable
        for k, v in request_config.items():
            if k not in ("configurable", "context"):
                config[k] = v
        # Never trust a client-supplied recursion_limit verbatim: clamp it to a
        # safe server range so a single run cannot execute unbounded LangGraph
        # super-steps (runaway LLM cost / DoS). Applied after the passthrough so
        # it overrides whatever the client sent.
        if "recursion_limit" in request_config:
            max_limit = _resolve_max_recursion_limit()
            clamped = _clamp_recursion_limit(request_config["recursion_limit"], max_limit)
            if clamped != request_config["recursion_limit"]:
                logger.warning(
                    "build_run_config: clamped client recursion_limit %r -> %d (max %d). thread_id=%s",
                    request_config["recursion_limit"],
                    clamped,
                    max_limit,
                    thread_id,
                )
            config["recursion_limit"] = clamped
    else:
        config["configurable"] = {"thread_id": thread_id}

    # Inject custom agent name when the caller specified a non-default assistant.
    # Honour an explicit agent_name in either runtime options container.
    if assistant_id and assistant_id != _DEFAULT_ASSISTANT_ID:
        normalized = assistant_id.strip().lower().replace("_", "-")
        if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
            raise ValueError(f"Invalid assistant_id {assistant_id!r}: must contain only letters, digits, and hyphens after normalization.")
        configurable = config.setdefault("configurable", {})
        runtime_context = config.setdefault("context", {})
        explicit_agent_name: str | None = None
        if isinstance(configurable, dict) and isinstance(configurable.get("agent_name"), str):
            explicit_agent_name = configurable["agent_name"]
        elif isinstance(runtime_context, dict) and isinstance(runtime_context.get("agent_name"), str):
            explicit_agent_name = runtime_context["agent_name"]
        effective_agent_name = explicit_agent_name or normalized
        if isinstance(configurable, dict):
            configurable["agent_name"] = effective_agent_name
        if isinstance(runtime_context, dict):
            runtime_context["agent_name"] = effective_agent_name
        config.setdefault("run_name", resolve_root_run_name(config, normalized))
    if metadata:
        config.setdefault("metadata", {}).update(metadata)
    return config


async def apply_checkpoint_to_run_config(
    config: dict[str, Any],
    *,
    body: Any,
    thread_id: str,
    request: Request,
) -> None:
    """验证请求指定的检查点属于当前线程且存在，再写入运行配置。"""
    checkpoint = getattr(body, "checkpoint", None)
    checkpoint_id = getattr(body, "checkpoint_id", None)
    checkpoint_ns = ""
    checkpoint_map = None

    if checkpoint:
        if not isinstance(checkpoint, Mapping):
            raise HTTPException(status_code=400, detail="checkpoint must be an object")
        checkpoint_thread_id = checkpoint.get("thread_id")
        if checkpoint_thread_id is not None and str(checkpoint_thread_id) != thread_id:
            raise HTTPException(status_code=400, detail="checkpoint thread_id does not match request thread_id")
        raw_checkpoint_id = checkpoint.get("checkpoint_id")
        if raw_checkpoint_id:
            checkpoint_id = str(raw_checkpoint_id)
        raw_checkpoint_ns = checkpoint.get("checkpoint_ns")
        if raw_checkpoint_ns is not None:
            checkpoint_ns = str(raw_checkpoint_ns)
        checkpoint_map = checkpoint.get("checkpoint_map")

    if not checkpoint_id:
        return

    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": str(checkpoint_id),
        }
    }
    if checkpoint_map is not None:
        read_config["configurable"]["checkpoint_map"] = checkpoint_map

    checkpointer = get_checkpointer(request)
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception as exc:
        logger.exception("Failed to validate checkpoint %s for thread %s", checkpoint_id, sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to validate checkpoint") from exc
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Checkpoint {checkpoint_id} not found")

    configurable = config.setdefault("configurable", {})
    if not isinstance(configurable, dict):
        raise HTTPException(status_code=400, detail="request config configurable must be an object")
    configurable["thread_id"] = thread_id
    configurable["checkpoint_ns"] = checkpoint_ns
    configurable["checkpoint_id"] = str(checkpoint_id)
    if checkpoint_map is not None:
        configurable["checkpoint_map"] = checkpoint_map


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_run(
    body: Any,
    thread_id: str,
    request: Request,
) -> RunRecord:
    """验证运行请求和线程权限，创建运行记录并启动后台 Agent 任务。"""
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    disconnect = DisconnectMode.cancel if body.on_disconnect == "cancel" else DisconnectMode.continue_

    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # Coerce non-string model_name values to str before truncation.
    if model_name is not None and not isinstance(model_name, str):
        model_name = str(model_name)

    # Validate model against the allowlist when a model_name is provided.
    if model_name:
        app_config = get_app_config()
        resolved = app_config.get_model_config(model_name)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"Model {model_name!r} is not in the configured model allowlist",
            )

    owner_user_id = get_trusted_internal_owner_user_id(request)
    # Stateless run endpoints carry thread_id in the request *body*, so the
    # @require_permission(owner_check=True) decorator -- which resolves ownership
    # from the path param -- cannot protect them. Enforce thread ownership here,
    # before any run is created, so one user cannot start runs on (or read /wait
    # checkpoint state from) another user's thread. Missing rows (auto-created
    # temp threads) and NULL-owner rows (shared / pre-auth data) stay accessible
    # via check_access; only a thread already owned by another user is rejected
    # with 404, matching thread_runs.py's anti-enumeration behaviour. Internal
    # channel runs act on behalf of the connection owner carried in
    # X-DeerFlow-Owner-User-Id, so they are scoped to that owner instead of
    # bypassing the check -- a leaked internal token must not grant cross-user
    # thread access.
    user = getattr(request.state, "user", None)
    if user is not None:
        allowed = await run_ctx.thread_store.check_access(thread_id, str(user.id))
        if not allowed and owner_user_id and getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
            # Channel workers may also act for the connection owner named in
            # the trusted header (e.g. claiming a legacy default-owned channel
            # thread for its real owner).
            allowed = await run_ctx.thread_store.check_access(thread_id, owner_user_id)
        if not allowed:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    owner_context_token = set_current_user(SimpleNamespace(id=owner_user_id)) if owner_user_id else None
    try:
        try:
            async with goal_thread_lock(thread_id):
                record = await run_mgr.create_or_reject(
                    thread_id,
                    body.assistant_id,
                    on_disconnect=disconnect,
                    metadata=body.metadata or {},
                    # Persist a secret-redacted copy of the config: the run record is
                    # written to runs.kwargs_json and echoed by the run API, so a
                    # request-scoped secret (#3861) must not ride along. The live
                    # config built below keeps the secrets for the actual run.
                    kwargs={"input": body.input, "config": redact_config_secrets(body.config)},
                    multitask_strategy=body.multitask_strategy,
                    model_name=model_name,
                    user_id=owner_user_id,
                )
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UnsupportedStrategyError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

        # Upsert thread metadata so the thread appears in /threads/search,
        # even for threads that were never explicitly created via POST /threads
        # (e.g. stateless runs).
        try:
            existing = await run_ctx.thread_store.get(thread_id)
            if existing is None and owner_user_id:
                unscoped_existing = await run_ctx.thread_store.get(thread_id, user_id=None)
                if unscoped_existing is not None:
                    if unscoped_existing.get("user_id") != owner_user_id:
                        await run_ctx.thread_store.update_owner(thread_id, owner_user_id, user_id=None)
                    existing = await run_ctx.thread_store.get(thread_id)
            if existing is None:
                await run_ctx.thread_store.create(
                    thread_id,
                    assistant_id=body.assistant_id,
                    metadata=body.metadata,
                )
            else:
                await run_ctx.thread_store.update_status(thread_id, "running")
        except Exception:
            logger.warning("Failed to upsert thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

        agent_factory = resolve_agent_factory(body.assistant_id)
        is_internal_caller = getattr(getattr(request, "state", None), "auth_source", None) == AUTH_SOURCE_INTERNAL
        command = getattr(body, "command", None)
        if command and command.get("resume") is not None:
            graph_input = Command(resume=command["resume"])
        else:
            graph_input = normalize_input(body.input, trusted_internal=is_internal_caller)
        config = build_run_config(thread_id, body.config, body.metadata, assistant_id=body.assistant_id)
        await apply_checkpoint_to_run_config(config, body=body, thread_id=thread_id, request=request)

        # Merge DeerFlow-specific context overrides into both ``configurable`` and ``context``.
        # The ``context`` field is a custom extension for the langgraph-compat layer
        # that carries agent configuration (model_name, thinking_enabled, etc.).
        # Only agent-relevant keys are forwarded; unknown keys (e.g. thread_id) are ignored.
        merge_run_context_overrides(config, getattr(body, "context", None), internal=is_internal_caller)
        if not is_internal_caller:
            # ``body.config`` is free-form and copied verbatim by
            # ``build_run_config``; scrub internal-only keys smuggled there.
            strip_internal_context_keys(config)
        internal_owner_user = await resolve_trusted_internal_owner_for_attribution(request, owner_user_id)
        inject_authenticated_user_context(config, request, internal_owner_user=internal_owner_user)

        stream_modes = normalize_stream_modes(body.stream_mode)

        task = asyncio.create_task(
            run_agent(
                bridge,
                run_mgr,
                record,
                ctx=run_ctx,
                agent_factory=agent_factory,
                graph_input=graph_input,
                config=config,
                stream_modes=stream_modes,
                stream_subgraphs=body.stream_subgraphs,
                interrupt_before=body.interrupt_before,
                interrupt_after=body.interrupt_after,
            )
        )
        record.task = task

        # Title sync is handled by worker.py's finally block which reads the
        # title from the checkpoint and calls thread_store.update_display_name
        # after the run completes.

        return record
    finally:
        if owner_context_token is not None:
            reset_current_user(owner_context_token)


async def launch_scheduled_thread_run(
    *,
    thread_id: str,
    assistant_id: str | None,
    prompt: str,
    request: Request | None = None,
    app: Any | None = None,
    owner_user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """以受信任的非交互上下文启动定时线程运行，并保持事件流和持久化记录一致。"""
    if request is None:
        if app is None:
            raise ValueError("launch_scheduled_thread_run requires request or app")
        request = SimpleNamespace(
            app=app,
            headers=({INTERNAL_OWNER_USER_ID_HEADER_NAME: owner_user_id} if owner_user_id else {}),
            state=SimpleNamespace(
                user=get_internal_user(),
                auth_source=AUTH_SOURCE_INTERNAL,
            ),
            cookies={},
        )
    # SimpleNamespace stands in for the Pydantic run-request body that the
    # HTTP path parses. If start_run gains a new body.* attribute that it reads
    # directly, add the matching field here so the scheduler path stays in sync.
    body = SimpleNamespace(
        assistant_id=assistant_id,
        input={"messages": [{"role": "user", "content": prompt}]},
        command=None,
        metadata=metadata or {},
        config=None,
        # ``user_id`` mirrors what IM channels put in ``body.context`` so
        # runtime-context consumers without a ContextVar fallback (e.g.
        # user-scoped GuardrailMiddleware providers) see the owning user;
        # ``inject_authenticated_user_context`` skips the internal user.
        context=({"non_interactive": True, "user_id": owner_user_id} if owner_user_id else {"non_interactive": True}),
        webhook=None,
        checkpoint_id=None,
        checkpoint=None,
        interrupt_before=None,
        interrupt_after=None,
        stream_mode=None,
        stream_subgraphs=False,
        stream_resumable=None,
        on_disconnect="continue",
        on_completion="keep",
        multitask_strategy="reject",
        after_seconds=None,
        if_not_exists="reject",
        feedback_keys=None,
    )
    record = await start_run(body, thread_id, request)
    return {"run_id": record.run_id, "thread_id": record.thread_id}


async def sse_consumer(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
):
    """订阅运行事件并编码为 SSE；客户端断开时按运行策略决定是否取消任务。"""
    last_event_id = request.headers.get("Last-Event-ID")
    if await _terminal_record_stream_missing(bridge, record):
        yield format_sse("end", None)
        return

    try:
        async for entry in bridge.subscribe(record.run_id, last_event_id=last_event_id):
            if await request.is_disconnected():
                break

            if entry is HEARTBEAT_SENTINEL:
                if await _terminal_record_stream_missing(bridge, record):
                    yield format_sse("end", None)
                    return
                yield ": heartbeat\n\n"
                continue

            if entry is END_SENTINEL:
                yield format_sse("end", None, event_id=entry.id or None)
                return

            yield format_sse(entry.event, entry.data, event_id=entry.id or None)

    finally:
        # store_only records are cross-worker runs hydrated from the RunStore; this
        # worker holds no in-memory task/abort state for them, so run_mgr.cancel()
        # cannot stop the task (it would 409). Skip on_disconnect cancellation for
        # those and only act on runs this worker actually owns.
        if not record.store_only and record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)


async def wait_for_run_completion(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
) -> bool:
    """等待事件桥发布运行终止标记；客户端断开时按策略取消任务并返回完成状态。"""
    completed = False
    if await _terminal_record_stream_missing(bridge, record):
        return True

    try:
        async for entry in bridge.subscribe(record.run_id):
            # END_SENTINEL means the run reached a terminal state; honour it
            # even if the client just disconnected so the caller still serializes
            # the real final checkpoint.
            if entry is END_SENTINEL:
                completed = True
                return True
            if entry is HEARTBEAT_SENTINEL and await _terminal_record_stream_missing(bridge, record):
                completed = True
                return True
            if await request.is_disconnected():
                break
            # Heartbeats and regular events: keep waiting for END_SENTINEL.
        return completed
    finally:
        if not completed and record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)
