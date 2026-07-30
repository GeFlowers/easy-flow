'定义 patched_openai 模块提供的职责与可复用接口。\n\nPatched ChatOpenAI that preserves thought_signature for Gemini thinking models.\n\nWhen using Gemini with thinking enabled via an OpenAI-compatible gateway (e.g.\nVertex AI, Google AI Studio, or any proxy), the API requires that the\n``thought_signature`` field on tool-call objects is echoed back verbatim in\nevery subsequent request.\n\nThe OpenAI-compatible gateway stores the raw tool-call dicts (including\n``thought_signature``) in ``additional_kwargs["tool_calls"]``, but standard\n``langchain_openai.ChatOpenAI`` only serialises the standard fields (``id``,\n``type``, ``function``) into the outgoing payload, silently dropping the\nsignature.  That causes an HTTP 400 ``INVALID_ARGUMENT`` error:\n\n    Unable to submit request because function call `<tool>` in the N. content\n    block is missing a `thought_signature`.\n\nThis module fixes the problem by overriding ``_get_request_payload`` to\nre-inject tool-call signatures back into the outgoing payload for any assistant\nmessage that originally carried them.\n'

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from deerflow.models.assistant_payload_replay import restore_assistant_payloads


class PatchedChatOpenAI(ChatOpenAI):
    '封装 PatchedChatOpenAI 的状态、协作关系与公开操作。\n\nChatOpenAI with ``thought_signature`` preservation for Gemini thinking via OpenAI gateway.\n\n    When using Gemini with thinking enabled via an OpenAI-compatible gateway,\n    the API expects ``thought_signature`` to be present on tool-call objects in\n    multi-turn conversations.  This patched version restores those signatures\n    from ``AIMessage.additional_kwargs["tool_calls"]`` into the serialised\n    request payload before it is sent to the API.\n\n    Usage in ``config.yaml``::\n\n        - name: gemini-2.5-pro-thinking\n          display_name: Gemini 2.5 Pro (Thinking)\n          use: deerflow.models.patched_openai:PatchedChatOpenAI\n          model: google/gemini-2.5-pro-preview\n          api_key: $GEMINI_API_KEY\n          base_url: https://<your-openai-compat-gateway>/v1\n          max_tokens: 16384\n          supports_thinking: true\n          supports_vision: true\n          when_thinking_enabled:\n            extra_body:\n              thinking:\n                type: enabled\n    '

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        '执行 _get_request_payload 的明确职责，并返回与调用约定一致的结果。\n\nGet request payload with ``thought_signature`` preserved on tool-call objects.\n\n        Overrides the parent method to re-inject ``thought_signature`` fields\n        on tool-call objects that were stored in\n        ``additional_kwargs["tool_calls"]`` by LangChain but dropped during\n        serialisation.\n        '
        # Capture the original LangChain messages *before* conversion so we can
        # access fields that the serialiser might drop.
        original_messages = self._convert_input(input_).to_messages()

        # Obtain the base payload from the parent implementation.
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        restore_assistant_payloads(payload.get("messages", []), original_messages, _restore_tool_call_signatures)

        return payload


def _restore_tool_call_signatures(payload_msg: dict, orig_msg: AIMessage) -> None:
    '执行 _restore_tool_call_signatures 的明确职责，并返回与调用约定一致的结果。\n\nRe-inject ``thought_signature`` onto tool-call objects in *payload_msg*.\n\n    When the Gemini OpenAI-compatible gateway returns a response with function\n    calls, each tool-call object may carry a ``thought_signature``.  LangChain\n    stores the raw tool-call dicts in ``additional_kwargs["tool_calls"]`` but\n    only serialises the standard fields (``id``, ``type``, ``function``) into\n    the outgoing payload, silently dropping the signature.\n\n    This function matches raw tool-call entries (by ``id``, falling back to\n    positional order) and copies the signature back onto the serialised\n    payload entries.\n    '
    raw_tool_calls: list[dict] = orig_msg.additional_kwargs.get("tool_calls") or []
    payload_tool_calls: list[dict] = payload_msg.get("tool_calls") or []

    if not raw_tool_calls or not payload_tool_calls:
        return

    # Build an id → raw_tc lookup for efficient matching.
    raw_by_id: dict[str, dict] = {}
    for raw_tc in raw_tool_calls:
        tc_id = raw_tc.get("id")
        if tc_id:
            raw_by_id[tc_id] = raw_tc

    for idx, payload_tc in enumerate(payload_tool_calls):
        # Try matching by id first, then fall back to positional.
        raw_tc = raw_by_id.get(payload_tc.get("id", ""))
        if raw_tc is None and idx < len(raw_tool_calls):
            raw_tc = raw_tool_calls[idx]

        if raw_tc is None:
            continue

        # The gateway may use either snake_case or camelCase.
        sig = raw_tc.get("thought_signature") or raw_tc.get("thoughtSignature")
        if sig:
            payload_tc["thought_signature"] = sig
