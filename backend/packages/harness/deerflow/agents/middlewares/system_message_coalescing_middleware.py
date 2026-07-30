'定义 system_message_coalescing_middleware 模块提供的职责与可复用接口。\n\nMiddleware to coalesce multiple SystemMessages into a single leading one.\n\nStrict OpenAI-compatible backends (vLLM, SGLang, Qwen) and Anthropic reject\nnon-leading SystemMessages with errors like "System message must be at the\nbeginning" or "Received multiple non-consecutive system messages". The\nofficial OpenAI API tolerates mid-conversation system messages, so the issue\nonly surfaces on strict backends.\n\nDeerFlow\'s lead agent accumulates multiple SystemMessages because\nDynamicContextMiddleware uses the ID-swap technique to replace the first or\nlast HumanMessage with a triplet whose first element is a SystemMessage\nreminder (framework-owned date/metadata must not masquerade as user input,\nper OWASP LLM01). On midnight crossings a second SystemMessage (date update)\nis injected. create_agent holds the static system_prompt in the separate\n``request.system_message`` field and only flattens it into the message list\ninside the model-call handler (``[request.system_message, *messages]``).\n\nThis middleware runs in wrap_model_call — before the handler flattens the two\n— and merges ``request.system_message`` plus every SystemMessage found in\n``request.messages`` into a single leading SystemMessage emitted via the\n``system_message`` field. It only touches the request payload; the persistent\nconversation state (checkpoint) is unchanged, so middleware that scans history\nby marker (e.g. is_dynamic_context_reminder) keeps working.\n\nNote: Mirrors the per-request coalescing already done for Claude in\nclaude_provider._coalesce_system_messages but at a provider-agnostic layer so\nevery backend benefits from a single fix instead of per-provider patches.\n'

from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from deerflow.agents.middlewares.dynamic_context_middleware import is_dynamic_context_reminder


def _flatten_content(content) -> str:
    '执行 _flatten_content 的明确职责，并返回与调用约定一致的结果。\n\nConvert message content to a plain string, handling both str and list types.\n\n    langchain messages support list-type content for multimodal (e.g.\n    ``[{"type": "text", "text": "..."}]``). SystemMessages in DeerFlow are always\n    plain strings, but this helper ensures robustness for any content shape.\n    '
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _coalesce_request(request: ModelRequest) -> ModelRequest | None:
    '执行 _coalesce_request 的明确职责，并返回与调用约定一致的结果。\n\nMerge ``request.system_message`` and in-``messages`` SystemMessages into one.\n\n    On langchain >= 1.2.15 the static system prompt lives in the separate\n    ``request.system_message`` field, not in ``request.messages``. The model-call\n    handler flattens them at the very last moment (``[system_message, *messages]``),\n    so a middleware that only scans ``messages`` cannot see the prompt and ends up\n    a no-op. This helper inspects both sources, merges every SystemMessage into a\n    single entry, and emits the result via ``system_message`` so the handler still\n    prepends it correctly.\n\n    Returns None when no SystemMessages live inside ``messages`` — in that case\n    ``system_message`` (if set) is already the sole leading system block and the\n    request can pass through with zero mutation, preserving prefix-cache hits.\n    '
    in_msg_systems = [m for m in request.messages if isinstance(m, SystemMessage)]
    if not in_msg_systems:
        return None

    # Merge system_message (if any) + all in-messages SystemMessages.
    parts: list[SystemMessage] = []
    if request.system_message is not None:
        parts.append(request.system_message)
    parts.extend(in_msg_systems)

    # Deduplicate dynamic_context_reminder SystemMessages: only keep the last
    # one (most recent date), drop earlier reminders. On midnight crossings
    # the merged content would otherwise contain two adjacent contradictory
    # <current_date> blocks with no temporal anchor — the intervening turns
    # that originally separated them are gone after coalescing. The model
    # should see only the latest date, not a stale one it must guess to
    # ignore.
    reminder_indices = [i for i, p in enumerate(parts) if is_dynamic_context_reminder(p)]
    if len(reminder_indices) > 1:
        keep_last = reminder_indices[-1]
        parts = [p for i, p in enumerate(parts) if i not in reminder_indices[:-1] or i == keep_last]

    # Preserve the id of the first SystemMessage (typically the static
    # system_prompt) so downstream consumers that key off the leading system
    # message id are unaffected. Merge additional_kwargs from all parts so
    # markers like hide_from_ui / dynamic_context_reminder from reminders are
    # retained on the coalesced block.
    first = parts[0]
    merged_kwargs: dict = {}
    for p in parts:
        merged_kwargs.update(p.additional_kwargs or {})
    merged = SystemMessage(
        content="\n\n".join(_flatten_content(p.content) for p in parts),
        id=first.id,
        additional_kwargs=merged_kwargs,
    )

    non_system = [m for m in request.messages if not isinstance(m, SystemMessage)]
    return request.override(system_message=merged, messages=non_system)


class SystemMessageCoalescingMiddleware(AgentMiddleware[AgentState]):
    '封装 SystemMessageCoalescingMiddleware 的状态、协作关系与公开操作。\n\nMerge all SystemMessages into a single leading SystemMessage.\n\n    Uses wrap_model_call (not before_agent) so the merge runs on the final\n    request payload — where ``system_message`` and ``messages`` are still\n    separate fields — and never touches the persisted state["messages"]. This\n    keeps the checkpoint structure intact for every consumer that scans history\n    (memory builder, journal, summarization, dynamic-context detection).\n    '

    @staticmethod
    def _maybe_coalesce(request: ModelRequest) -> ModelRequest:
        '执行 _maybe_coalesce 的明确职责，并返回与调用约定一致的结果'
        coalesced = _coalesce_request(request)
        if coalesced is None:
            return request
        return coalesced

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        '执行 wrap_model_call 的明确职责，并返回与调用约定一致的结果'
        return handler(self._maybe_coalesce(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        '执行 awrap_model_call 的明确职责，并返回与调用约定一致的结果'
        return await handler(self._maybe_coalesce(request))
