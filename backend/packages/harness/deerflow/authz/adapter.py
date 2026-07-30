'未说明'

from __future__ import annotations

from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal
from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class GuardrailAuthorizationAdapter:
    '未说明guardrail?authorization未说明'

    name = "authorization"

    def __init__(
        self,
        provider: AuthorizationProvider,
        *,
        resource_type: str = "tool",
        action: str = "call",
    ) -> None:
        '未说明'
        self._provider = provider
        self._resource_type = resource_type
        self._action = action

    def _to_authz(self, gr: GuardrailRequest) -> AuthzRequest:
        '未说明to未说明'
        return AuthzRequest(
            principal=Principal(
                user_id=gr.user_id,
                role=gr.user_role,
                oauth_provider=gr.oauth_provider,
                oauth_id=gr.oauth_id,
            ),
            resource=self._resource_type,
            action=self._action,
            target=gr.tool_name,
            context={
                "thread_id": gr.thread_id,
                "run_id": gr.run_id,
                "tool_call_id": gr.tool_call_id,
                "tool_input": gr.tool_input,
                "is_subagent": gr.is_subagent,
                "agent_id": gr.agent_id,
                "timestamp": gr.timestamp,
            },
        )

    @staticmethod
    def _to_guardrail(d: AuthzDecision) -> GuardrailDecision:
        '未说明to?guardrail未说明'
        return GuardrailDecision(
            allow=d.allow,
            reasons=[GuardrailReason(code=r.code, message=r.message) for r in d.reasons],
            policy_id=d.policy_id,
            metadata=d.metadata,
        )

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '未说明evaluate未说明'
        decision = self._provider.authorize(self._to_authz(request))
        return self._to_guardrail(decision)

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '未说明aevaluate未说明'
        decision = await self._provider.aauthorize(self._to_authz(request))
        return self._to_guardrail(decision)
