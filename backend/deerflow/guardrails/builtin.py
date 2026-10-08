'''提供无需外部服务的内置工具白名单和黑名单判定器。'''

from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class AllowlistProvider:
    '''按允许列表和拒绝列表决定某个工具调用是否继续执行。'''

    name = "allowlist"

    def __init__(self, *, allowed_tools: list[str] | None = None, denied_tools: list[str] | None = None):
        '''保存允许和拒绝集合，并区分未配置允许列表与显式空列表。'''
        self._allowed = set(allowed_tools) if allowed_tools is not None else None
        self._denied = set(denied_tools) if denied_tools else set()

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '''按工具名称应用允许列表和拒绝列表，生成放行或拒绝决定。'''
        if self._allowed is not None and request.tool_name not in self._allowed:
            return GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.tool_not_allowed", message=f"tool '{request.tool_name}' not in allowlist")])
        if request.tool_name in self._denied:
            return GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.tool_not_allowed", message=f"tool '{request.tool_name}' is denied")])
        return GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.allowed")])

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '''提供异步判定接口，并复用同步的列表校验逻辑。'''
        return self.evaluate(request)
