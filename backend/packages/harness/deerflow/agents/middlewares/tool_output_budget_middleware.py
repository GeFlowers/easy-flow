'定义 tool_output_budget_middleware 模块提供的职责与可复用接口。\n\nMiddleware that enforces a per-result budget on tool outputs.\n\nOversized tool results are persisted to disk and replaced with a compact\npreview containing a file reference.  When disk persistence is\nunavailable the middleware falls back to head+tail truncation so the\nmodel context is never blown by a single large tool return.\n'

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING, Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.sandbox.sandbox_provider import get_sandbox_provider

if TYPE_CHECKING:
    from deerflow.sandbox.sandbox import Sandbox

logger = logging.getLogger(__name__)

# Virtual outputs root inside the sandbox. Host-mounted sandboxes map this to
# the thread outputs dir on the host; for non-mounted (remote) sandboxes the
# same path is written directly into the sandbox filesystem so the model's
# ``read_file`` tool can read it back (issue #3416).
_VIRTUAL_OUTPUTS_BASE = "/mnt/user-data/outputs"


def _default_config() -> ToolOutputConfig:
    """创建默认的工具输出预算配置。"""
    return ToolOutputConfig()


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _message_text(content: Any) -> str | None:
    '执行 _message_text 的明确职责，并返回与调用约定一致的结果。\n\nExtract a plain-text representation from a ToolMessage content field.\n\n    Returns ``None`` for non-string / multimodal content so the caller\n    can skip budget enforcement (images, structured blocks, etc.).\n    '
    if isinstance(content, str):
        return content
    if content is None:
        return None
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                pieces.append(part["text"])
            else:
                return None
        return "\n".join(pieces) if pieces else None
    return None


def _snap_to_line_boundary(text: str, pos: int) -> int:
    '执行 _snap_to_line_boundary 的明确职责，并返回与调用约定一致的结果。\n\nReturn *pos* or the nearest preceding newline+1, whichever is closer.\n\n    Used so that previews and truncations end on a complete line when\n    possible.  If no newline exists in the second half of ``text[:pos]``\n    the original *pos* is returned unchanged.\n\n    Only valid for an *end* offset: moving backwards shortens the slice that\n    ends here.  Use :func:`_snap_start_to_line_boundary` for a start offset.\n    '
    if pos <= 0 or pos >= len(text):
        return pos
    half = pos // 2
    nl = text.rfind("\n", half, pos)
    if nl >= 0:
        return nl + 1
    return pos


def _snap_start_to_line_boundary(text: str, pos: int) -> int:
    '执行 _snap_start_to_line_boundary 的明确职责，并返回与调用约定一致的结果。\n\nReturn *pos* or the nearest following newline+1, whichever is closer.\n\n    The start-offset mirror of :func:`_snap_to_line_boundary`. Snapping a start\n    backwards would *lengthen* the slice beginning there, so the tail of a\n    budgeted preview must snap forward instead. If no newline exists in the\n    first half of ``text[pos:]`` the original *pos* is returned unchanged.\n    '
    if pos <= 0 or pos >= len(text):
        return pos
    half = pos + (len(text) - pos) // 2
    nl = text.find("\n", pos, half)
    if nl >= 0:
        return nl + 1
    return pos


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------

_EXT_MAP: dict[str, str] = {
    "bash": "log",
    "bash_tool": "log",
    "web_fetch": "log",
}


def _sanitize_tool_name(name: str) -> str:
    '执行 _sanitize_tool_name 的明确职责，并返回与调用约定一致的结果。\n\nStrip path separators and traversal components from a tool name.'
    base = os.path.basename(name)
    safe = base.replace("..", "").replace("/", "_").replace("\\", "_")
    return safe or "unknown"


def _build_externalized_filename(*, tool_name: str, tool_call_id: str) -> str:
    '执行 _build_externalized_filename 的明确职责，并返回与调用约定一致的结果。\n\nBuild the on-disk filename for an externalized tool output.\n\n    Shared by the host-disk and sandbox externalization paths so both\n    produce the identical naming scheme.\n    '
    safe_name = _sanitize_tool_name(tool_name)
    ext = _EXT_MAP.get(tool_name, "txt")
    short_id = uuid.uuid4().hex[:12]
    return f"{safe_name}-{short_id}.{ext}"


def _externalize(
    content: str,
    *,
    tool_name: str,
    tool_call_id: str,
    outputs_path: str,
    storage_subdir: str,
) -> str | None:
    '执行 _externalize 的明确职责，并返回与调用约定一致的结果。\n\nWrite *content* to disk and return the virtual path, or ``None`` on failure.'
    if os.path.isabs(storage_subdir) or ".." in storage_subdir:
        return None
    storage_dir = os.path.join(outputs_path, storage_subdir)
    try:
        os.makedirs(storage_dir, exist_ok=True)
    except OSError:
        return None

    filename = _build_externalized_filename(tool_name=tool_name, tool_call_id=tool_call_id)
    filepath = os.path.join(storage_dir, filename)

    if not os.path.abspath(filepath).startswith(os.path.abspath(storage_dir)):
        return None

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        return None

    return f"{_VIRTUAL_OUTPUTS_BASE}/{storage_subdir}/{filename}"


def _externalize_to_sandbox(
    content: str,
    *,
    tool_name: str,
    tool_call_id: str,
    storage_subdir: str,
    sandbox: Sandbox,
) -> str | None:
    "执行 _externalize_to_sandbox 的明确职责，并返回与调用约定一致的结果。\n\nWrite *content* into the sandbox filesystem and return the virtual path.\n\n    Used when the sandbox does not use thread-data mounts (e.g. a remote AIO\n    sandbox): the host-side :func:`_externalize` virtual path would not exist\n    inside the sandbox, so the model's ``read_file`` tool could not read it\n    back (issue #3416). Returns the same virtual-path contract on success, or\n    ``None`` to signal the caller to fall back to inline truncation.\n    "
    if os.path.isabs(storage_subdir) or ".." in storage_subdir:
        return None
    filename = _build_externalized_filename(tool_name=tool_name, tool_call_id=tool_call_id)
    virtual_dir = f"{_VIRTUAL_OUTPUTS_BASE}/{storage_subdir}"
    virtual_path = f"{virtual_dir}/{filename}"
    try:
        # AIO sandbox write_file does NOT create parent directories, so create
        # them explicitly before writing. execute_command returns its stdout
        # verbatim (including an "Error: ..." string on failure) rather than
        # raising, so we cannot rely on exception propagation here.
        sandbox.execute_command(f"mkdir -p {shlex.quote(virtual_dir)}")
        sandbox.write_file(virtual_path, content)
        # Validate the file landed: execute_command may have silently failed
        # to create the directory, and write_file backends differ. Refuse to
        # hand the model an unreadable read_file path.
        check = sandbox.execute_command(f"test -s {shlex.quote(virtual_path)} && echo OK || echo MISSING")
        if not isinstance(check, str) or check.strip() != "OK":
            logger.warning(
                "Sandbox externalize validation failed: path=%s, check=%r",
                virtual_path,
                check,
            )
            return None
    except Exception:
        logger.exception(
            "Failed to externalize %s output to sandbox (call_id=%s)",
            tool_name,
            tool_call_id,
        )
        return None
    return virtual_path


# ---------------------------------------------------------------------------
# Preview / fallback builders
# ---------------------------------------------------------------------------


def _build_preview(
    content: str,
    *,
    tool_name: str,
    virtual_path: str,
    head_chars: int,
    tail_chars: int,
) -> str:
    '执行 _build_preview 的明确职责，并返回与调用约定一致的结果。\n\nBuild a preview with a file reference for externalized output.'
    total = len(content)
    head_end = _snap_to_line_boundary(content, min(head_chars, total))
    tail_start = max(head_end, total - tail_chars)
    tail_start_snapped = _snap_to_line_boundary(content, tail_start)
    if tail_start_snapped > head_end:
        tail_start = tail_start_snapped

    head = content[:head_end]
    tail = content[tail_start:] if tail_start < total else ""

    omitted = total - len(head) - len(tail)
    ref = f"\n\n[Full {tool_name} output saved to {virtual_path} ({total} chars, ~{total // 4} tokens). Use read_file with start_line and end_line to access specific sections. {omitted} chars omitted from this preview.]\n\n"

    parts = [head, ref]
    if tail:
        parts.append(tail)
    return "".join(parts)


def _build_fallback(
    content: str,
    *,
    tool_name: str,
    max_chars: int,
    head_chars: int,
    tail_chars: int,
) -> str:
    '执行 _build_fallback 的明确职责，并返回与调用约定一致的结果。\n\nBuild a head+tail truncation when disk persistence is unavailable.\n\n    The returned string is guaranteed to be no longer than *max_chars*.\n    '
    total = len(content)
    if max_chars <= 0 or total <= max_chars:
        return content

    marker_template = "\n\n[... {n} chars omitted from {tn} output. Persistent storage unavailable. Consider narrowing the query or using more specific parameters.]\n\n"
    marker_overhead = len(marker_template.format(n=total, tn=tool_name))

    if marker_overhead >= max_chars:
        return content[:max_chars]

    budget = max_chars - marker_overhead
    effective_head = min(head_chars, budget)
    effective_tail = min(tail_chars, max(0, budget - effective_head))

    head_end = _snap_to_line_boundary(content, min(effective_head, total))
    tail_start = _snap_start_to_line_boundary(content, max(head_end, total - effective_tail))

    head = content[:head_end]
    tail = content[tail_start:] if tail_start < total else ""
    omitted = total - len(head) - len(tail)

    marker = marker_template.format(n=omitted, tn=tool_name)

    parts = [head, marker]
    if tail:
        parts.append(tail)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Core budget logic
# ---------------------------------------------------------------------------


def _resolve_outputs_path(request: ToolCallRequest) -> str | None:
    '执行 _resolve_outputs_path 的明确职责，并返回与调用约定一致的结果。\n\nBest-effort extraction of the thread outputs path.'
    runtime = getattr(request, "runtime", None)
    if runtime is None:
        return None
    state = getattr(runtime, "state", None)
    if state is None:
        return None
    thread_data = state.get("thread_data")
    if not isinstance(thread_data, dict):
        return None
    outputs_path = thread_data.get("outputs_path")
    return outputs_path if isinstance(outputs_path, str) else None


def _resolve_sandbox(request: ToolCallRequest) -> Sandbox | None:
    '执行 _resolve_sandbox 的明确职责，并返回与调用约定一致的结果。\n\nResolve the active sandbox for the current tool call, or ``None``.\n\n    Reads the sandbox_id that ``SandboxMiddleware`` (and the sandbox tools\n    themselves) write into ``runtime.state["sandbox"]``. We intentionally do\n    NOT call ``provider.acquire`` here: acquiring a sandbox can trigger\n    blocking remote I/O, and this resolver runs on every tool call. Tools\n    that do not use a sandbox (``web_search``, MCP, ...) will return ``None``\n    here, which is fine -- the caller falls back to inline truncation.\n    '
    runtime = getattr(request, "runtime", None)
    state = getattr(runtime, "state", None)
    if not isinstance(state, dict):
        return None
    sandbox_state = state.get("sandbox")
    if not isinstance(sandbox_state, dict):
        return None
    sandbox_id = sandbox_state.get("sandbox_id")
    if not sandbox_id:
        return None
    try:
        return get_sandbox_provider().get(sandbox_id)
    except Exception:
        logger.exception("Failed to look up sandbox %s for tool-output externalization", sandbox_id)
        return None


def _budget_content(
    content: str,
    *,
    tool_name: str,
    tool_call_id: str,
    outputs_path: str | None,
    config: ToolOutputConfig,
    sandbox: Sandbox | None = None,
) -> str | None:
    '执行 _budget_content 的明确职责，并返回与调用约定一致的结果。\n\nApply budget to *content*. Returns ``None`` if no change needed.'
    threshold = config.tool_overrides.get(tool_name, config.externalize_min_chars)
    if threshold <= 0 and config.fallback_max_chars <= 0:
        return None
    if len(content) <= threshold and len(content) <= config.fallback_max_chars:
        return None

    if threshold > 0 and len(content) > threshold:
        virtual_path: str | None = None
        # Decide persistence target based on what's available, without touching
        # the sandbox provider unless a sandbox was actually resolved for this
        # call. This keeps the legacy host-disk path provider-free, so callers
        # without a configured sandbox (and CI environments without a
        # config.yaml) continue to externalize to the host as before.
        if sandbox is not None:
            provider = None
            try:
                provider = get_sandbox_provider()
            except Exception:
                logger.exception("Failed to get sandbox provider for tool-output externalization; falling back to inline truncation")
            if provider is not None and getattr(provider, "uses_thread_data_mounts", False):
                # Host-mounted sandbox: host outputs path is bind-mounted into
                # the sandbox at the same virtual path, so writing host-side is
                # equivalent. Preserve the original behavior to avoid extra
                # sandbox round-trips.
                if outputs_path:
                    virtual_path = _externalize(
                        content,
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        outputs_path=outputs_path,
                        storage_subdir=config.storage_subdir,
                    )
            else:
                virtual_path = _externalize_to_sandbox(
                    content,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    storage_subdir=config.storage_subdir,
                    sandbox=sandbox,
                )
        elif outputs_path:
            # No sandbox in this call (legacy / non-sandbox tools): write to
            # host outputs path directly, no provider needed.
            virtual_path = _externalize(
                content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                outputs_path=outputs_path,
                storage_subdir=config.storage_subdir,
            )
        if virtual_path is not None:
            logger.info(
                "Externalized %s output (%d chars) to %s",
                tool_name,
                len(content),
                virtual_path,
            )
            return _build_preview(
                content,
                tool_name=tool_name,
                virtual_path=virtual_path,
                head_chars=config.preview_head_chars,
                tail_chars=config.preview_tail_chars,
            )

    if config.fallback_max_chars > 0 and len(content) > config.fallback_max_chars:
        logger.warning(
            "Fallback-truncating %s output: %d chars → %d max",
            tool_name,
            len(content),
            config.fallback_max_chars,
        )
        return _build_fallback(
            content,
            tool_name=tool_name,
            max_chars=config.fallback_max_chars,
            head_chars=config.fallback_head_chars,
            tail_chars=config.fallback_tail_chars,
        )

    return None


# ---------------------------------------------------------------------------
# Result patchers
# ---------------------------------------------------------------------------


def _patch_tool_message(
    msg: ToolMessage,
    config: ToolOutputConfig,
    outputs_path: str | None,
    sandbox: Sandbox | None = None,
) -> ToolMessage:
    '执行 _patch_tool_message 的明确职责，并返回与调用约定一致的结果。\n\nApply budget to a single ToolMessage. Returns the original if unchanged.'
    tool_name = msg.name or "unknown"
    if tool_name in config.exempt_tools:
        return msg

    text = _message_text(msg.content)
    if text is None:
        return msg

    replacement = _budget_content(
        text,
        tool_name=tool_name,
        tool_call_id=msg.tool_call_id or "",
        outputs_path=outputs_path,
        config=config,
        sandbox=sandbox,
    )
    if replacement is None:
        return msg

    update: dict[str, Any] = {"content": replacement}
    if getattr(msg, "response_metadata", None):
        update["response_metadata"] = dict(msg.response_metadata)
    if getattr(msg, "additional_kwargs", None):
        update["additional_kwargs"] = dict(msg.additional_kwargs)
    return msg.model_copy(update=update)


def _effective_trigger(tool_name: str, config: ToolOutputConfig) -> int:
    '执行 _effective_trigger 的明确职责，并返回与调用约定一致的结果。\n\nSmallest content length that could trigger budgeting for *tool_name*.\n\n    Mirrors the trigger conditions in :func:`_budget_content` (per-tool\n    externalize threshold OR global fallback), so the pre-scan never produces\n    a false negative. Returns ``-1`` when nothing could ever trigger.\n    '
    candidates: list[int] = []
    externalize = config.tool_overrides.get(tool_name, config.externalize_min_chars)
    if externalize > 0:
        candidates.append(externalize)
    if config.fallback_max_chars > 0:
        candidates.append(config.fallback_max_chars)
    return min(candidates) if candidates else -1


def _tool_message_over_budget(msg: ToolMessage, config: ToolOutputConfig) -> bool:
    '执行 _tool_message_over_budget 的明确职责，并返回与调用约定一致的结果。\n\nCheap, per-tool-aware check: is this ToolMessage non-exempt and over its trigger?'
    if (msg.name or "") in config.exempt_tools:
        return False
    trigger = _effective_trigger(msg.name or "", config)
    if trigger < 0:
        return False
    text = _message_text(msg.content)
    return text is not None and len(text) > trigger


def _needs_budget(result: ToolMessage | Command, config: ToolOutputConfig) -> bool:
    '执行 _needs_budget 的明确职责，并返回与调用约定一致的结果。\n\nFast check whether *result* could need budgeting (avoids thread offload for small outputs).'
    if isinstance(result, ToolMessage):
        return _tool_message_over_budget(result, config)
    update = getattr(result, "update", None)
    if isinstance(update, dict):
        for msg in update.get("messages", []):
            if isinstance(msg, ToolMessage) and _tool_message_over_budget(msg, config):
                return True
    return False


def _patch_result(
    result: ToolMessage | Command,
    config: ToolOutputConfig,
    outputs_path: str | None,
    sandbox: Sandbox | None = None,
) -> ToolMessage | Command:
    '执行 _patch_result 的明确职责，并返回与调用约定一致的结果。\n\nApply budget to a tool call result (ToolMessage or Command).'
    if isinstance(result, ToolMessage):
        return _patch_tool_message(result, config, outputs_path, sandbox)

    update = getattr(result, "update", None)
    if not isinstance(update, dict):
        return result

    messages = update.get("messages")
    if not isinstance(messages, list):
        return result

    new_messages: list[Any] = []
    changed = False
    for msg in messages:
        if isinstance(msg, ToolMessage):
            patched = _patch_tool_message(msg, config, outputs_path, sandbox)
            if patched is not msg:
                changed = True
            new_messages.append(patched)
        else:
            new_messages.append(msg)

    if not changed:
        return result

    return dc_replace(result, update={**update, "messages": new_messages})


def _patch_model_messages(messages: list[Any], config: ToolOutputConfig) -> list[Any] | None:
    '执行 _patch_model_messages 的明确职责，并返回与调用约定一致的结果。\n\nApply budget to historical ToolMessages in a model request. Returns ``None`` if unchanged.\n\n    A cheap pre-scan bails out before allocating a new list when no historical\n    ToolMessage exceeds the budget — the common case once every result has\n    already been budgeted at tool-call time, so a long history is not rebuilt\n    on every model call.\n\n    Historical messages do not get a ``sandbox`` argument: any oversized tool\n    message in history was already budgeted (and possibly externalized) at\n    tool-call time, so the only thing left for the history path to do is\n    inline fallback truncation, which needs no sandbox.\n    '
    if not any(isinstance(msg, ToolMessage) and _tool_message_over_budget(msg, config) for msg in messages):
        return None

    updated: list[Any] = []
    changed = False
    for msg in messages:
        if isinstance(msg, ToolMessage):
            patched = _patch_tool_message(msg, config, outputs_path=None)
            if patched is not msg:
                changed = True
            updated.append(patched)
        else:
            updated.append(msg)
    return updated if changed else None


# ---------------------------------------------------------------------------
# Middleware class
# ---------------------------------------------------------------------------


class ToolOutputBudgetMiddleware(AgentMiddleware[AgentState]):
    '封装 ToolOutputBudgetMiddleware 的状态、协作关系与公开操作。\n\nEnforce per-result budget on tool outputs via externalization or truncation.'

    def __init__(self, config: ToolOutputConfig | None = None) -> None:
        """使用给定或默认配置初始化工具输出预算中间件。"""
        super().__init__()
        self._config = config if config is not None else _default_config()

    @classmethod
    def from_app_config(cls, app_config: Any) -> ToolOutputBudgetMiddleware:
        """从应用配置中读取工具输出预算设置并构造中间件。"""
        tool_output = getattr(app_config, "tool_output", None)
        if isinstance(tool_output, ToolOutputConfig):
            return cls(config=tool_output)
        return cls()

    # -- tool call hooks ---------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """同步执行工具调用，并对超预算结果外置或截断。"""
        result = handler(request)
        if not self._config.enabled:
            return result
        if not _needs_budget(result, self._config):
            return result
        outputs_path = _resolve_outputs_path(request)
        sandbox = _resolve_sandbox(request)
        return _patch_result(result, self._config, outputs_path, sandbox)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """异步执行工具调用，并在线程中处理超预算结果。"""
        result = await handler(request)
        if not self._config.enabled:
            return result
        if not _needs_budget(result, self._config):
            return result
        outputs_path = _resolve_outputs_path(request)
        # _resolve_sandbox only touches runtime.state and the provider's
        # in-memory sandbox registry, so it is safe to call on the event
        # loop. The actual sandbox I/O (mkdir/write/test) happens inside
        # _patch_result, which is offloaded to a worker thread below.
        sandbox = _resolve_sandbox(request)
        return await asyncio.to_thread(_patch_result, result, self._config, outputs_path, sandbox)

    # -- model call hooks (historical message truncation) ------------------

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """在同步模型调用前截断历史中超预算的工具消息。"""
        if self._config.enabled:
            messages = getattr(request, "messages", None)
            if isinstance(messages, list):
                patched = _patch_model_messages(messages, self._config)
                if patched is not None:
                    request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """在异步模型调用前截断历史中超预算的工具消息。"""
        if self._config.enabled:
            messages = getattr(request, "messages", None)
            if isinstance(messages, list):
                patched = _patch_model_messages(messages, self._config)
                if patched is not None:
                    request = request.override(messages=patched)
        return await handler(request)
