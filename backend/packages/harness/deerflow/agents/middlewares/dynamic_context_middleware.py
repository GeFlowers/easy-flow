'定义 dynamic_context_middleware 模块提供的职责与可复用接口。\n\nMiddleware to inject dynamic context (memory, current date) as a system-reminder.\n\nThe system prompt is kept fully static for maximum prefix-cache reuse across users\nand sessions.  The current date is always injected.  Per-user memory is also injected\nwhen ``memory.injection_enabled`` is True in the app config.  Both are delivered once\nper conversation as a dedicated <system-reminder> SystemMessage inserted before the\nfirst user message (frozen-snapshot pattern).\n\nWhen a conversation spans midnight the middleware detects the date change and injects\na lightweight date-update reminder as a separate SystemMessage before the current turn.\nThis correction is persisted so subsequent turns on the new day see a consistent history\nand do not re-inject.\n\nReminder format:\n\n    <system-reminder>\n    <memory>...</memory>\n\n    <current_date>2026-05-08, Friday</current_date>\n    </system-reminder>\n\nDate-update format:\n\n    <system-reminder>\n    <current_date>2026-05-09, Saturday</current_date>\n    </system-reminder>\n'

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

# Upper bound (seconds) for a single _inject() offload.  If the warm-up at
# gateway startup failed silently, the first request may still hit a cold
# tiktoken BPE download that blocks until the OS TCP timeout (~26 min).
# This cap ensures the request degrades gracefully instead of hanging.
_INJECT_TIMEOUT_SECONDS = 5.0

_DATE_RE = re.compile(r"<current_date>([^<]+)</current_date>")
_DYNAMIC_CONTEXT_REMINDER_KEY = "dynamic_context_reminder"
# Authoritative injected date, carried in additional_kwargs of the date
# SystemMessage. Detection reads this instead of regex-parsing message content,
# so it is never exposed to user-influenceable memory content.
_REMINDER_DATE_KEY = "reminder_date"
_SUMMARY_MESSAGE_NAME = "summary"


def _extract_date(content: str) -> str | None:
    '执行 _extract_date 的明确职责，并返回与调用约定一致的结果。\n\nReturn the first <current_date> value found in *content*, or None.'
    m = _DATE_RE.search(content)
    return m.group(1) if m else None


def is_dynamic_context_reminder(message: object) -> bool:
    '判断条件是否成立并返回布尔结果，并遵守 is_dynamic_context_reminder 所表达的接口约束。\n\nReturn whether *message* is a hidden dynamic-context reminder.'
    # DEPRECATED: HumanMessage reminders only exist in pre-PR checkpoints.
    # Once all active checkpoints are migrated, the HumanMessage branch can be
    # removed and this function can check SystemMessage exclusively.
    return isinstance(message, (HumanMessage, SystemMessage)) and bool(message.additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY))


def _last_injected_date(messages: list) -> str | None:
    '执行 _last_injected_date 的明确职责，并返回与调用约定一致的结果。\n\nScan messages in reverse and return the most recently injected date.\n\n    Detection uses the ``dynamic_context_reminder`` additional_kwargs flag rather\n    than content substring matching, so user messages containing ``<system-reminder>``\n    are not mistakenly treated as injected reminders.\n\n    The authoritative date is the ``reminder_date`` value in additional_kwargs of\n    the date SystemMessage. Reminders without it (the separate ``<memory>``\n    HumanMessage, or any future dateless reminder) carry no date and are skipped,\n    so they cannot shadow the real date reminder.\n    '
    for msg in reversed(messages):
        if not is_dynamic_context_reminder(msg):
            continue
        structured = msg.additional_kwargs.get(_REMINDER_DATE_KEY)
        if isinstance(structured, str) and structured:
            return structured
        # Backward-compat for checkpoints written before reminder_date existed:
        # the date lived in content. Scope the regex to SystemMessage so it never
        # runs on the user-influenceable memory HumanMessage (preserves the OWASP
        # role separation from #3630 and closes the memory date-spoofing hole).
        if isinstance(msg, SystemMessage):
            content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
            date = _extract_date(content_str)
            if date is not None:
                return date
    return None


def _is_user_injection_target(message: object) -> bool:
    '执行 _is_user_injection_target 的明确职责，并返回与调用约定一致的结果。\n\nReturn whether *message* can receive a dynamic-context reminder.'
    if not isinstance(message, HumanMessage):
        return False
    if is_dynamic_context_reminder(message):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    # Prevent recursive ID-swap: a message whose ID ends with "__user" was
    # produced by a prior _make_reminder_and_user_messages call and must not
    # be processed again — doing so causes unbounded suffix growth
    # (id__user__user__user...) and ghost-message re-execution.
    # Using endswith (not substring "in") avoids false positives on IDs that
    # happen to contain "__user" in the middle.
    if message.id and str(message.id).endswith("__user"):
        return False
    return True


class DynamicContextMiddleware(AgentMiddleware):
    '封装 DynamicContextMiddleware 的状态、协作关系与公开操作。\n\nInject memory and current date as a SystemMessage <system-reminder>.\n\n    First turn\n    ----------\n    Prepends a full system-reminder (memory + date) to the first HumanMessage and\n    persists it (same message ID).  The first message is then frozen for the whole\n    session — its content never changes again, so the prefix cache can hit on every\n    subsequent turn.\n\n    Midnight crossing\n    -----------------\n    If the conversation spans midnight, the current date differs from the date that\n    was injected earlier.  In that case a lightweight date-update reminder is prepended\n    to the **current** (last) HumanMessage and persisted.  Subsequent turns on the new\n    day see the corrected date in history and skip re-injection.\n    '

    def __init__(self, agent_name: str | None = None, *, app_config: AppConfig | None = None):
        """使用代理名称与可选应用配置初始化动态上下文中间件。"""
        super().__init__()
        self._agent_name = agent_name
        self._app_config = app_config

    def _build_full_reminder(self) -> tuple[str, str | None]:
        '执行 _build_full_reminder 的明确职责，并返回与调用约定一致的结果。\n\nReturn (date_reminder, memory_block | None).\n\n        Framework-owned data (date) is separated from user-owned data (memory)\n        so the downstream SystemMessage carries only framework authority and\n        memory stays at role:user — preventing untrusted content from gaining\n        system privilege (OWASP LLM01).\n        '
        from deerflow.agents.lead_agent.prompt import _get_memory_context

        injection_enabled = self._app_config.memory.injection_enabled if self._app_config else True
        memory_context = _get_memory_context(self._agent_name, app_config=self._app_config) if injection_enabled else ""
        current_date = datetime.now().strftime("%Y-%m-%d, %A")

        date_reminder = "\n".join(
            [
                "<system-reminder>",
                f"<current_date>{current_date}</current_date>",
                "</system-reminder>",
            ]
        )

        memory_block = memory_context.strip() if memory_context else None

        return date_reminder, memory_block

    def _build_date_update_reminder(self) -> str:
        """构造仅包含当前日期的跨日更新提醒。"""
        current_date = datetime.now().strftime("%Y-%m-%d, %A")
        return "\n".join(
            [
                "<system-reminder>",
                f"<current_date>{current_date}</current_date>",
                "</system-reminder>",
            ]
        )

    @staticmethod
    def _make_reminder_and_user_messages(
        original: HumanMessage,
        reminder_content: str,
        memory_content: str | None = None,
        *,
        reminder_date: str | None = None,
    ) -> list[SystemMessage | HumanMessage]:
        '执行 _make_reminder_and_user_messages 的明确职责，并返回与调用约定一致的结果。\n\nReturn messages using the ID-swap technique.\n\n        SystemMessage carries framework-owned data (date, metadata) — takes\n        the original ID so add_messages replaces it in-place.  *reminder_date*\n        is recorded in its additional_kwargs as the authoritative injected date\n        (``_last_injected_date`` reads it instead of parsing content).  Optional\n        HumanMessage carries user-owned memory content with ``{id}__memory``.\n        The actual user message gets ``{id}__user``.\n\n        SystemMessage is used — system context must not masquerade as user\n        input (#3630).  Memory is deliberately kept as HumanMessage so\n        user-influenceable content does not gain system authority (OWASP LLM01)\n        — and it deliberately never carries ``reminder_date``.\n        '
        stable_id = original.id or str(uuid.uuid4())
        messages: list[SystemMessage | HumanMessage] = []

        reminder_kwargs = {"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True}
        if reminder_date is not None:
            reminder_kwargs[_REMINDER_DATE_KEY] = reminder_date
        messages.append(
            SystemMessage(
                content=reminder_content,
                id=stable_id,
                additional_kwargs=reminder_kwargs,
            )
        )

        if memory_content:
            messages.append(
                HumanMessage(
                    content=memory_content,
                    id=f"{stable_id}__memory",
                    additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
                )
            )

        messages.append(
            HumanMessage(
                content=original.content,
                id=f"{stable_id}__user",
                name=original.name,
                additional_kwargs=original.additional_kwargs,
            )
        )
        return messages

    def _inject(self, state) -> dict | None:
        """为目标用户消息生成并注入当前日期及可选记忆提醒。"""
        messages = list(state.get("messages", []))
        if not messages:
            return None

        current_date = datetime.now().strftime("%Y-%m-%d, %A")
        last_date = _last_injected_date(messages)
        logger.debug(
            "DynamicContextMiddleware._inject: msg_count=%d last_date=%r current_date=%r",
            len(messages),
            last_date,
            current_date,
        )

        if last_date is None:
            # ── First turn: inject full reminder as a SystemMessage ─────
            first_idx = next((i for i, m in enumerate(messages) if _is_user_injection_target(m)), None)
            if first_idx is None:
                return None
            date_reminder, memory_block = self._build_full_reminder()
            logger.info(
                "DynamicContextMiddleware: injecting full reminder (has_memory=%s) into first HumanMessage id=%r",
                memory_block is not None,
                messages[first_idx].id,
            )
            result_msgs = self._make_reminder_and_user_messages(messages[first_idx], date_reminder, memory_block, reminder_date=current_date)
            return {"messages": result_msgs}

        if last_date == current_date:
            # ── Same day: nothing to do ──────────────────────────────────────────
            return None

        # ── Midnight crossed: inject date-update reminder as a SystemMessage ──
        last_human_idx = next((i for i in reversed(range(len(messages))) if _is_user_injection_target(messages[i])), None)
        if last_human_idx is None:
            return None

        result_msgs = self._make_reminder_and_user_messages(messages[last_human_idx], self._build_date_update_reminder(), reminder_date=current_date)
        logger.info("DynamicContextMiddleware: midnight crossing detected — injected date update before current turn")
        return {"messages": result_msgs}

    @override
    def before_agent(self, state, runtime: Runtime) -> dict | None:
        """在同步代理执行前注入本轮所需的动态上下文。"""
        result = self._inject(state)
        self._record_effective_memory(state, result, runtime)
        return result

    @override
    async def abefore_agent(self, state, runtime: Runtime) -> dict | None:
        """在线程池中异步注入本轮所需的动态上下文。"""
        # _inject() performs synchronous file I/O (memory JSON loading) and
        # potentially blocking network calls (tiktoken encoding download on
        # first use).  Offload to a thread so the event loop is never blocked
        # — a blocking call here starves all concurrent HTTP handlers (auth,
        # SSE heartbeats, etc.).  See issue #3402.
        #
        # Bounded timeout: if startup warm-up failed silently (e.g. network
        # blip during deploy), the first request's cold tiktoken download can
        # block for tens of minutes (OS TCP timeout).  Time-box injection so
        # the request degrades gracefully (no new dynamic-context update)
        # rather than hanging. Frozen context already in state remains active.
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._inject, state),
                timeout=_INJECT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "DynamicContextMiddleware: injection timed out (%.1fs); skipping new memory/date injection for this turn",
                _INJECT_TIMEOUT_SECONDS,
            )
            self._record_effective_memory(state, None, runtime)
            return None
        self._record_effective_memory(state, result, runtime)
        return result

    @staticmethod
    def _effective_memory_message(state, update: dict | None, runtime: Runtime) -> HumanMessage | None:
        "执行 _effective_memory_message 的明确职责，并返回与调用约定一致的结果。\n\nFind server-created memory that is effective for this run.\n\n        A first-run block must come from this middleware's update. A reused\n        block must have existed in the checkpoint before the run; the Gateway\n        strips the reminder marker from untrusted input so a caller cannot\n        replace a known checkpoint ID with forged provenance.\n        "
        if isinstance(update, dict):
            update_messages = update.get("messages")
            if isinstance(update_messages, list):
                for message in update_messages:
                    if not isinstance(message, HumanMessage):
                        continue
                    message_id = str(message.id or "")
                    if message_id.endswith("__memory") and is_dynamic_context_reminder(message) and isinstance(message.content, str):
                        return message

        context = getattr(runtime, "context", None)
        raw_pre_existing_ids = context.get(CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY) if isinstance(context, dict) else None
        if not isinstance(raw_pre_existing_ids, (frozenset, set, list, tuple)):
            return None
        pre_existing_ids = {str(message_id) for message_id in raw_pre_existing_ids if message_id}
        for message in state.get("messages", []):
            if not isinstance(message, HumanMessage):
                continue
            message_id = str(message.id or "")
            if message_id in pre_existing_ids and message_id.endswith("__memory") and is_dynamic_context_reminder(message) and isinstance(message.content, str):
                return message
        return None

    def _record_effective_memory(self, state, update: dict | None, runtime: Runtime) -> None:
        '执行 _record_effective_memory 的明确职责，并返回与调用约定一致的结果。\n\nAttach the effective hidden memory block to the current run ledger.'
        context = getattr(runtime, "context", None)
        journal = context.get("__run_journal") if isinstance(context, dict) else None
        if journal is None:
            return

        message = self._effective_memory_message(state, update, runtime)
        if message is None:
            return

        try:
            journal.record_memory_context(
                content_sha256=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
            )
        except Exception:
            logger.debug("Failed to record effective memory context", exc_info=True)
