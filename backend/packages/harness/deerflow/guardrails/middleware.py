'定义 middleware 模块提供的职责与可复用接口。\n\nGuardrailMiddleware - evaluates tool calls against a GuardrailProvider before execution.'

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.guardrails.provider import GuardrailDecision, GuardrailProvider, GuardrailReason, GuardrailRequest

logger = logging.getLogger(__name__)

_REASON_MESSAGE_LIMIT = 500


class GuardrailMiddleware(AgentMiddleware[AgentState]):
    '封装 GuardrailMiddleware 的状态、协作关系与公开操作。\n\nEvaluate tool calls against a GuardrailProvider before execution.\n\n    Denied calls return an error ToolMessage so the agent can adapt.\n    If the provider raises, behavior depends on fail_closed:\n      - True (default): block the call\n      - False: allow it through with a warning\n    '

    def __init__(self, provider: GuardrailProvider, *, fail_closed: bool = True, passport: str | None = None):
        '实现 __init__ 协议方法，保持对象交互语义一致'
        self.provider = provider
        self.fail_closed = fail_closed
        self.passport = passport

    @staticmethod
    def _resolve_context(request: ToolCallRequest) -> dict:
        '执行 _resolve_context 的明确职责，并返回与调用约定一致的结果'
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None) if runtime is not None else None
        return context if isinstance(context, dict) else {}

    def _build_request(self, request: ToolCallRequest, context: dict) -> GuardrailRequest:
        '执行 _build_request 的明确职责，并返回与调用约定一致的结果'
        return GuardrailRequest(
            tool_name=str(request.tool_call.get("name", "")),
            tool_input=request.tool_call.get("args", {}),
            agent_id=self.passport,
            thread_id=context.get("thread_id"),
            is_subagent=bool(context.get("is_subagent")),
            timestamp=datetime.now(UTC).isoformat(),
            user_id=context.get("user_id"),
            user_role=context.get("user_role"),
            oauth_provider=context.get("oauth_provider"),
            oauth_id=context.get("oauth_id"),
            run_id=context.get("run_id"),
            tool_call_id=request.tool_call.get("id"),
        )

    def _build_denied_message(self, request: ToolCallRequest, decision: GuardrailDecision) -> ToolMessage:
        '执行 _build_denied_message 的明确职责，并返回与调用约定一致的结果'
        tool_name = str(request.tool_call.get("name", "unknown_tool"))
        tool_call_id = str(request.tool_call.get("id", "missing_id"))
        reason_text = decision.reasons[0].message if decision.reasons else "blocked by guardrail policy"
        reason_code = decision.reasons[0].code if decision.reasons else "oap.denied"
        return ToolMessage(
            content=f"Guardrail denied: tool '{tool_name}' was blocked ({reason_code}). Reason: {reason_text}. Choose an alternative approach.",
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )

    def _record_guardrail_event(
        self,
        context: dict,
        guardrail_request: GuardrailRequest,
        decision: GuardrailDecision,
        *,
        action: str,
        provider_error: bool,
    ) -> None:
        '执行 _record_guardrail_event 的明确职责，并返回与调用约定一致的结果。\n\nPersist a security-relevant guardrail decision to RunJournal.\n\n        This follows the optional-Journal pattern used by existing middleware:\n        audit persistence is best-effort and must never change tool execution\n        behavior. Runtimes without ``__run_journal`` (including embedded and\n        subagent execution) skip persistence.\n        '
        journal = context.get("__run_journal")
        if journal is None:
            return

        reason_codes = [reason.code for reason in decision.reasons if reason.code]
        reason_messages = [reason.message[:_REASON_MESSAGE_LIMIT] for reason in decision.reasons if reason.message]

        changes = {
            "tool_name": guardrail_request.tool_name,
            "tool_call_id": guardrail_request.tool_call_id,
            "agent_id": guardrail_request.agent_id,
            # Native subagents do not currently inherit __run_journal; custom
            # runtimes may still provide one with subagent attribution.
            "is_subagent": guardrail_request.is_subagent,
            "user_role": guardrail_request.user_role,
            "allow": decision.allow,
            "policy_id": decision.policy_id,
            "reason_codes": reason_codes,
            "reason_messages": reason_messages,
            "fail_closed": self.fail_closed,
            "provider_error": provider_error,
        }

        try:
            journal.record_middleware(
                tag="guardrail",
                name=type(self).__name__,
                hook="wrap_tool_call",
                action=action,
                changes=changes,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to record middleware:guardrail event", exc_info=True)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        '执行 wrap_tool_call 的明确职责，并返回与调用约定一致的结果'
        context = self._resolve_context(request)
        gr = self._build_request(request, context)
        try:
            decision = self.provider.evaluate(gr)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception:
            logger.exception("Guardrail provider error (sync)")
            if self.fail_closed:
                decision = GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.evaluator_error", message="guardrail provider error (fail-closed)")])
                self._record_guardrail_event(
                    context,
                    gr,
                    decision,
                    action="deny_tool_call",
                    provider_error=True,
                )
                return self._build_denied_message(request, decision)
            else:
                decision = GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.evaluator_error", message="guardrail provider error (fail-open)")])
                self._record_guardrail_event(
                    context,
                    gr,
                    decision,
                    action="allow_tool_call_after_provider_error",
                    provider_error=True,
                )
                return handler(request)
        if not decision.allow:
            logger.warning("Guardrail denied: tool=%s policy=%s code=%s", gr.tool_name, decision.policy_id, decision.reasons[0].code if decision.reasons else "unknown")
            self._record_guardrail_event(
                context,
                gr,
                decision,
                action="deny_tool_call",
                provider_error=False,
            )
            return self._build_denied_message(request, decision)
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        '执行 awrap_tool_call 的明确职责，并返回与调用约定一致的结果'
        context = self._resolve_context(request)
        gr = self._build_request(request, context)
        try:
            decision = await self.provider.aevaluate(gr)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception:
            logger.exception("Guardrail provider error (async)")
            if self.fail_closed:
                decision = GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.evaluator_error", message="guardrail provider error (fail-closed)")])
                self._record_guardrail_event(
                    context,
                    gr,
                    decision,
                    action="deny_tool_call",
                    provider_error=True,
                )
                return self._build_denied_message(request, decision)
            else:
                decision = GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.evaluator_error", message="guardrail provider error (fail-open)")])
                self._record_guardrail_event(
                    context,
                    gr,
                    decision,
                    action="allow_tool_call_after_provider_error",
                    provider_error=True,
                )
                return await handler(request)
        if not decision.allow:
            logger.warning("Guardrail denied: tool=%s policy=%s code=%s", gr.tool_name, decision.policy_id, decision.reasons[0].code if decision.reasons else "unknown")
            self._record_guardrail_event(
                context,
                gr,
                decision,
                action="deny_tool_call",
                provider_error=False,
            )
            return self._build_denied_message(request, decision)
        return await handler(request)
