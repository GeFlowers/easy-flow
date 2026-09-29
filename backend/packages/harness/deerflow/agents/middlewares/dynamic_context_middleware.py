"""定义 dynamic_context_middleware 模块提供的职责与可复用接口。

Middleware to inject dynamic context (memory, current date) as a system-reminder.

The system prompt is kept fully static for maximum prefix-cache reuse across users
and sessions.  The current date is always injected.  Per-user memory is also injected
when ``memory.injection_enabled`` is True in the app config.  Both are delivered once
per conversation as a dedicated <system-reminder> SystemMessage inserted before the
first user message (frozen-snapshot pattern).

When a conversation spans midnight the middleware detects the date change and injects
a lightweight date-update reminder as a separate SystemMessage before the current turn.
This correction is persisted so subsequent turns on the new day see a consistent history
and do not re-inject.

Reminder format:

    <system-reminder>
    <memory>...</memory>

    <current_date>2026-05-08, Friday</current_date>
    </system-reminder>

Date-update format:

    <system-reminder>
    <current_date>2026-05-09, Saturday</current_date>
    </system-reminder>
"""

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
# 日期标记写入 SystemMessage 的结构化元数据；识别时不扫描可能受用户影响的记忆文本。
_REMINDER_DATE_KEY = "reminder_date"
_SUMMARY_MESSAGE_NAME = "summary"


def _extract_date(content: str) -> str | None:
    """提取内容中第一个 ``<current_date>`` 标签的日期值。"""
    m = _DATE_RE.search(content)
    return m.group(1) if m else None


def is_dynamic_context_reminder(message: object) -> bool:
    """判断消息是否带有动态上下文提醒的内部标记。"""
    # 兼容旧检查点中以 HumanMessage 保存的提醒；新消息使用 SystemMessage。
    return isinstance(message, (HumanMessage, SystemMessage)) and bool(message.additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY))


def _last_injected_date(messages: list) -> str | None:
    """从消息末尾向前寻找最近注入的日期，优先读取结构化元数据并兼容旧检查点。"""
    for msg in reversed(messages):
        if not is_dynamic_context_reminder(msg):
            continue
        structured = msg.additional_kwargs.get(_REMINDER_DATE_KEY)
        if isinstance(structured, str) and structured:
            return structured
        # 旧检查点把日期写在内容中；仅解析 SystemMessage，避免用户可影响的记忆文本伪造日期。
        if isinstance(msg, SystemMessage):
            content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
            date = _extract_date(content_str)
            if date is not None:
                return date
    return None


def _is_user_injection_target(message: object) -> bool:
    """判断人类消息是否适合插入动态提醒，排除摘要、已有提醒及已处理消息。"""
    if not isinstance(message, HumanMessage):
        return False
    if is_dynamic_context_reminder(message):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    # 由拆分流程生成的用户消息带有 __user 后缀；再次处理会不断追加后缀并重复执行消息。
    # 使用 endswith 可避免误排除仅在中间包含该字符串的其他 ID。
    if message.id and str(message.id).endswith("__user"):
        return False
    return True


class DynamicContextMiddleware(AgentMiddleware):
    """封装 DynamicContextMiddleware 的状态、协作关系与公开操作。

    Inject memory and current date as a SystemMessage <system-reminder>.

        First turn
        ----------
        Prepends a full system-reminder (memory + date) to the first HumanMessage and
        persists it (same message ID).  The first message is then frozen for the whole
        session — its content never changes again, so the prefix cache can hit on every
        subsequent turn.

        Midnight crossing
        -----------------
        If the conversation spans midnight, the current date differs from the date that
        was injected earlier.  In that case a lightweight date-update reminder is prepended
        to the **current** (last) HumanMessage and persisted.  Subsequent turns on the new
        day see the corrected date in history and skip re-injection.
    """

    def __init__(self, agent_name: str | None = None, *, app_config: AppConfig | None = None):
        """使用代理名称与可选应用配置初始化动态上下文中间件。"""
        super().__init__()
        self._agent_name = agent_name
        self._app_config = app_config

    def _build_full_reminder(self) -> tuple[str, str | None]:
        """执行 _build_full_reminder 的明确职责，并返回与调用约定一致的结果。

        Return (date_reminder, memory_block | None).

                Framework-owned data (date) is separated from user-owned data (memory)
                so the downstream SystemMessage carries only framework authority and
                memory stays at role:user — preventing untrusted content from gaining
                system privilege (OWASP LLM01).
        """
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
        """执行 _make_reminder_and_user_messages 的明确职责，并返回与调用约定一致的结果。

        Return messages using the ID-swap technique.

                SystemMessage carries framework-owned data (date, metadata) — takes
                the original ID so add_messages replaces it in-place.  *reminder_date*
                is recorded in its additional_kwargs as the authoritative injected date
                (``_last_injected_date`` reads it instead of parsing content).  Optional
                HumanMessage carries user-owned memory content with ``{id}__memory``.
                The actual user message gets ``{id}__user``.

                SystemMessage is used — system context must not masquerade as user
                input (#3630).  Memory is deliberately kept as HumanMessage so
                user-influenceable content does not gain system authority (OWASP LLM01)
                — and it deliberately never carries ``reminder_date``.
        """
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
        """执行 _effective_memory_message 的明确职责，并返回与调用约定一致的结果。

        Find server-created memory that is effective for this run.

                A first-run block must come from this middleware's update. A reused
                block must have existed in the checkpoint before the run; the Gateway
                strips the reminder marker from untrusted input so a caller cannot
                replace a known checkpoint ID with forged provenance.
        """
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
        """执行 _record_effective_memory 的明确职责，并返回与调用约定一致的结果。

        Attach the effective hidden memory block to the current run ledger."""
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
