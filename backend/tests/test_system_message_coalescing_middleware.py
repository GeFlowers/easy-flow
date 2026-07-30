'未说明'

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from deerflow.agents.middlewares.system_message_coalescing_middleware import (
    SystemMessageCoalescingMiddleware,
    _coalesce_request,
    _flatten_content,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(system_message: SystemMessage | None, messages: list[BaseMessage]):
    '未说明'
    request = MagicMock()
    request.system_message = system_message
    request.messages = list(messages)
    request.override = lambda **updates: _override_request(request, updates)
    return request


def _override_request(request, updates):
    '未说明'
    new = MagicMock()
    new.system_message = updates.get("system_message", request.system_message)
    new.messages = updates.get("messages", request.messages)
    new.override = lambda **kw: _override_request(new, kw)
    return new


def _capture_handler():
    '未说明'
    captured = []

    def handler(req):
        '未说明'
        captured.append(req)
        return "response"

    return captured, handler


def _final_payload(request) -> list[BaseMessage]:
    '未说明'
    if request.system_message is not None:
        return [request.system_message, *request.messages]
    return list(request.messages)


# ===========================================================================
# _coalesce_request (pure helper)
# ===========================================================================


class TestCoalesceRequest:
    '未说明'
    def test_no_system_anywhere_returns_none(self):
        '未说明'
        request = _make_request(system_message=None, messages=[HumanMessage(content="hi")])
        assert _coalesce_request(request) is None

    def test_only_system_message_field_returns_none(self):
        '未说明'
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[HumanMessage(content="hi")],
        )
        assert _coalesce_request(request) is None

    def test_system_message_plus_one_in_msg_system_coalesces(self):
        '未说明'
        prompt = SystemMessage(content="You are DeerFlow.", id="sys-1")
        reminder = SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1")
        user = HumanMessage(content="Hello", id="msg-1__user")
        request = _make_request(system_message=prompt, messages=[reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message is not None
        assert "You are DeerFlow." in result.system_message.content
        assert "<system-reminder>date</system-reminder>" in result.system_message.content
        # messages no longer contain any SystemMessage
        assert not any(isinstance(m, SystemMessage) for m in result.messages)
        # user message preserved
        assert any(m.content == "Hello" for m in result.messages)

    def test_system_message_plus_two_in_msg_systems_coalesces(self):
        '未说明'
        prompt = SystemMessage(content="prompt")
        reminder = SystemMessage(content="<system-reminder>day1</system-reminder>")
        date_update = SystemMessage(content="<system-reminder>day2</system-reminder>")
        user = HumanMessage(content="next")
        request = _make_request(system_message=prompt, messages=[reminder, date_update, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "day1" in result.system_message.content
        assert "day2" in result.system_message.content

    def test_no_system_message_but_in_msg_systems_coalesces(self):
        '未说明'
        reminder = SystemMessage(content="reminder")
        user = HumanMessage(content="hi")
        request = _make_request(system_message=None, messages=[reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message is not None
        assert "reminder" in result.system_message.content
        assert not any(isinstance(m, SystemMessage) for m in result.messages)

    def test_merged_content_uses_double_newline_separator(self):
        '未说明'
        prompt = SystemMessage(content="PART_A")
        reminder = SystemMessage(content="PART_B")
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.content == "PART_A\n\nPART_B"

    def test_merged_preserves_first_system_message_id(self):
        '未说明'
        prompt = SystemMessage(content="prompt", id="sys-1")
        reminder = SystemMessage(content="reminder", id="msg-1")
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.id == "sys-1"

    def test_merged_preserves_in_msg_id_when_no_system_message(self):
        '未说明'
        reminder = SystemMessage(content="reminder", id="msg-1")
        request = _make_request(system_message=None, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.id == "msg-1"

    def test_non_system_messages_keep_original_order(self):
        '未说明'
        prompt = SystemMessage(content="prompt")
        user1 = HumanMessage(content="u1", id="u1")
        ai = AIMessage(content="a1", id="a1")
        reminder = SystemMessage(content="reminder")
        user2 = HumanMessage(content="u2", id="u2")
        request = _make_request(system_message=prompt, messages=[user1, ai, reminder, user2])

        result = _coalesce_request(request)
        assert result is not None
        non_system = result.messages
        assert [m.id for m in non_system] == ["u1", "a1", "u2"]

    def test_merged_kwargs_combine_all_parts(self):
        '未说明'
        prompt = SystemMessage(
            content="prompt",
            id="sys-1",
            additional_kwargs={"source": "prompt"},
        )
        reminder = SystemMessage(
            content="reminder",
            id="msg-1",
            additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
        )
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.additional_kwargs == {
            "source": "prompt",
            "hide_from_ui": True,
            "dynamic_context_reminder": True,
        }

    def test_merged_kwargs_later_parts_override(self):
        '未说明'
        prompt = SystemMessage(
            content="prompt",
            id="sys-1",
            additional_kwargs={"priority": "low"},
        )
        reminder = SystemMessage(
            content="reminder",
            id="msg-1",
            additional_kwargs={"priority": "high"},
        )
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.additional_kwargs["priority"] == "high"

    def test_merged_handles_list_content(self):
        '未说明'
        prompt = SystemMessage(
            content=[{"type": "text", "text": "You are DeerFlow."}],
            id="sys-1",
        )
        reminder = SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1")
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert "You are DeerFlow." in result.system_message.content
        assert "<system-reminder>date</system-reminder>" in result.system_message.content

    def test_reminder_dedup_keeps_only_last(self):
        '未说明'
        prompt = SystemMessage(content="prompt", id="sys-prompt")
        day1 = SystemMessage(
            content="<system-reminder>day1</system-reminder>",
            id="msg-1",
            additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
        )
        day2 = SystemMessage(
            content="<system-reminder>day2</system-reminder>",
            id="msg-2",
            additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
        )
        user = HumanMessage(content="hi")
        request = _make_request(system_message=prompt, messages=[day1, day2, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "day2" in result.system_message.content
        assert "day1" not in result.system_message.content

    def test_reminder_dedup_does_not_affect_non_reminder_systems(self):
        '未说明'
        prompt = SystemMessage(content="prompt", id="sys-prompt")
        other = SystemMessage(content="custom system block", id="msg-1")
        reminder = SystemMessage(
            content="<system-reminder>day2</system-reminder>",
            id="msg-2",
            additional_kwargs={"dynamic_context_reminder": True},
        )
        user = HumanMessage(content="hi")
        request = _make_request(system_message=prompt, messages=[other, reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "custom system block" in result.system_message.content
        assert "day2" in result.system_message.content

    def test_single_reminder_not_deduplicated(self):
        '未说明'
        prompt = SystemMessage(content="prompt", id="sys-prompt")
        reminder = SystemMessage(
            content="<system-reminder>date</system-reminder>",
            id="msg-1",
            additional_kwargs={"dynamic_context_reminder": True},
        )
        user = HumanMessage(content="hi")
        request = _make_request(system_message=prompt, messages=[reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "date" in result.system_message.content


# ===========================================================================
# _flatten_content (pure helper)
# ===========================================================================


class TestFlattenContent:
    '未说明'
    def test_string_content_returns_same_string(self):
        '未说明'
        assert _flatten_content("hello") == "hello"

    def test_list_of_strings(self):
        '未说明'
        assert _flatten_content(["line1", "line2"]) == "line1\nline2"

    def test_list_of_text_dicts(self):
        '未说明'
        content = [{"type": "text", "text": "paragraph1"}, {"type": "text", "text": "paragraph2"}]
        assert _flatten_content(content) == "paragraph1\nparagraph2"

    def test_mixed_list(self):
        '未说明'
        content = ["plain", {"type": "text", "text": "dict"}, 42]
        assert _flatten_content(content) == "plain\ndict\n42"

    def test_non_string_non_list(self):
        '未说明'
        assert _flatten_content(42) == "42"


# ===========================================================================
# SystemMessageCoalescingMiddleware.wrap_model_call
# ===========================================================================


class TestWrapModelCall:
    '未说明'
    def test_passthrough_when_no_in_msg_systems(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[HumanMessage(content="hi")],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)
        assert captured[0] is request

    def test_override_called_when_in_msg_systems_present(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[SystemMessage(content="reminder"), HumanMessage(content="hi")],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        sent = captured[0]
        assert sent is not request  # overridden
        assert sent.system_message is not None
        assert "prompt" in sent.system_message.content
        assert "reminder" in sent.system_message.content
        assert not any(isinstance(m, SystemMessage) for m in sent.messages)

    def test_returns_handler_result(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[SystemMessage(content="reminder")],
        )
        handler = MagicMock(return_value="llm-response")

        result = mw.wrap_model_call(request, handler)
        assert result == "llm-response"


# ===========================================================================
# SystemMessageCoalescingMiddleware.awrap_model_call
# ===========================================================================


class TestAwrapModelCall:
    '未说明'
    @pytest.mark.asyncio
    async def test_async_passthrough_no_in_msg_systems(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[HumanMessage(content="hi")],
        )
        captured = []

        async def handler(req):
            '未说明'
            captured.append(req)
            return "async-response"

        result = await mw.awrap_model_call(request, handler)
        assert result == "async-response"
        assert captured[0] is request

    @pytest.mark.asyncio
    async def test_async_coalesces_in_msg_systems(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[SystemMessage(content="reminder"), HumanMessage(content="hi")],
        )
        captured = []

        async def handler(req):
            '未说明'
            captured.append(req)
            return "ok"

        result = await mw.awrap_model_call(request, handler)
        assert result == "ok"
        sent = captured[0]
        assert sent is not request
        assert "prompt" in sent.system_message.content
        assert "reminder" in sent.system_message.content


# ===========================================================================
# Realistic scenario: DynamicContextMiddleware ID-swap + create_agent prompt
# ===========================================================================


class TestRealisticScenario:
    '未说明'
    def test_first_turn_single_system_message_in_final_payload(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        # Real shape: system_prompt in system_message field, reminder in messages
        request = _make_request(
            system_message=SystemMessage(content="You are DeerFlow 2.0, an AI assistant...", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>\n<current_date>2026-06-22, Monday</current_date>\n</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
                ),
                HumanMessage(content="<memory>User prefers Python.</memory>", id="msg-1__memory"),
                HumanMessage(content="What is the capital of France?", id="msg-1__user"),
            ],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        # Simulate what the LLM receives: [system_message, *messages]
        sent = captured[0]
        final = _final_payload(sent)
        system_count = sum(1 for m in final if isinstance(m, SystemMessage))
        assert system_count == 1  # key assertion: only 1 SystemMessage
        assert "DeerFlow 2.0" in final[0].content
        assert "<current_date>2026-06-22, Monday</current_date>" in final[0].content
        # User-owned memory stays as HumanMessage (OWASP LLM01 preserved)
        assert any(isinstance(m, HumanMessage) and "User prefers Python." in m.content for m in final)
        assert any(isinstance(m, HumanMessage) and m.content == "What is the capital of France?" for m in final)

    def test_midnight_crossing_single_system_message_in_final_payload(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="system prompt", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>day1</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
                ),
                HumanMessage(content="<memory>...</memory>", id="msg-1__memory"),
                HumanMessage(content="first question", id="msg-1__user"),
                AIMessage(content="first answer", id="ai-1"),
                SystemMessage(
                    content="<system-reminder>day2</system-reminder>",
                    id="msg-2",
                    additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
                ),
                HumanMessage(content="second question", id="msg-2__user"),
            ],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        sent = captured[0]
        final = _final_payload(sent)
        system_count = sum(1 for m in final if isinstance(m, SystemMessage))
        assert system_count == 1
        merged = final[0]
        assert "system prompt" in merged.content
        # Only the latest date survives; the stale day1 reminder is dropped.
        assert "day2" in merged.content
        assert "day1" not in merged.content
        # Non-system messages in order
        non_system = [m for m in final if not isinstance(m, SystemMessage)]
        assert [m.content for m in non_system] == [
            "<memory>...</memory>",
            "first question",
            "first answer",
            "second question",
        ]

    def test_no_system_message_field_but_in_msg_systems(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=None,
            messages=[
                SystemMessage(content="reminder", id="msg-1"),
                HumanMessage(content="hi"),
            ],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        sent = captured[0]
        final = _final_payload(sent)
        system_count = sum(1 for m in final if isinstance(m, SystemMessage))
        assert system_count == 1
        assert "reminder" in final[0].content


# ===========================================================================
# Strict-backend stub: end-to-end test against vLLM/SGLang/Qwen rejection
# ===========================================================================


class StrictBackendError(Exception):
    '未说明'


def _strict_backend_handler(request):
    '未说明'
    final = _final_payload(request)
    system_count = sum(1 for m in final if isinstance(m, SystemMessage))
    if system_count > 1:
        raise StrictBackendError("Received multiple system messages")
    if system_count == 1 and not isinstance(final[0], SystemMessage):
        raise StrictBackendError("System message must be at the beginning")
    return "ok"


async def _async_strict_backend_handler(request):
    '未说明'
    return _strict_backend_handler(request)


class TestStrictBackendStub:
    '未说明'

    def test_first_turn_without_middleware_rejects(self):
        '未说明'
        request = _make_request(
            system_message=SystemMessage(content="You are DeerFlow.", id="sys-prompt"),
            messages=[
                SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1"),
                HumanMessage(content="Hello", id="msg-1__user"),
            ],
        )
        # Final payload: [sys-prompt, reminder, __user] → 2 SystemMessages
        # → strict backend rejects: multiple system messages
        with pytest.raises(StrictBackendError):
            _strict_backend_handler(request)

    def test_first_turn_with_middleware_accepts(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="You are DeerFlow.", id="sys-prompt"),
            messages=[
                SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1"),
                HumanMessage(content="Hello", id="msg-1__user"),
            ],
        )
        result = mw.wrap_model_call(request, _strict_backend_handler)
        assert result == "ok"

    def test_midnight_crossing_without_middleware_rejects(self):
        '未说明'
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>day1</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q1", id="msg-1__user"),
                AIMessage(content="a1", id="ai-1"),
                SystemMessage(
                    content="<system-reminder>day2</system-reminder>",
                    id="msg-2",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q2", id="msg-2__user"),
            ],
        )
        with pytest.raises(StrictBackendError):
            _strict_backend_handler(request)

    def test_midnight_crossing_with_middleware_accepts(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>day1</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q1", id="msg-1__user"),
                AIMessage(content="a1", id="ai-1"),
                SystemMessage(
                    content="<system-reminder>day2</system-reminder>",
                    id="msg-2",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q2", id="msg-2__user"),
            ],
        )
        result = mw.wrap_model_call(request, _strict_backend_handler)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_async_path_with_middleware_accepts(self):
        '未说明'
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[
                SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1"),
                HumanMessage(content="Hello", id="msg-1__user"),
            ],
        )
        result = await mw.awrap_model_call(request, _async_strict_backend_handler)
        assert result == "ok"

    def test_clean_request_no_middleware_needed(self):
        '未说明'
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[HumanMessage(content="hi")],
        )
        # No middleware needed — single SystemMessage at position 0
        result = _strict_backend_handler(request)
        assert result == "ok"
