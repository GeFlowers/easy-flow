'''把通用授权提供方接入工具调用防护流程，并转换两套请求与决策结构。'''

from __future__ import annotations

from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal
from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class GuardrailAuthorizationAdapter:
    '''作为防护提供方适配器，将工具调用上下文交给授权策略判定。'''

    name = "authorization"

    def __init__(
        self,
        provider: AuthorizationProvider,
        *,
        resource_type: str = "tool",
        action: str = "call",
    ) -> None:
        '''保存授权后端及本适配器默认使用的资源类别和操作名称。'''
        self._provider = provider
        self._resource_type = resource_type
        self._action = action

    def _to_authz(self, gr: GuardrailRequest) -> AuthzRequest:
        '''将防护层提供的用户、工具和运行上下文映射成授权请求。'''
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
        '''把授权结果及理由转换为防护中间件可处理的决策对象。'''
        return GuardrailDecision(
            allow=d.allow,
            reasons=[GuardrailReason(code=r.code, message=r.message) for r in d.reasons],
            policy_id=d.policy_id,
            metadata=d.metadata,
        )

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '''同步执行授权检查，并返回防护调用链使用的判定结果。'''
        decision = self._provider.authorize(self._to_authz(request))
        return self._to_guardrail(decision)

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '''异步执行授权检查，并返回防护调用链使用的判定结果。'''
        decision = await self._provider.aauthorize(self._to_authz(request))
        return self._to_guardrail(decision)
