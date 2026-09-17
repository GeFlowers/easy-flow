"""定义 builtin 模块提供的职责与可复用接口。

Built-in guardrail providers that ship with DeerFlow."""

from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class AllowlistProvider:
    """封装 AllowlistProvider 的状态、协作关系与公开操作。

    Simple allowlist/denylist provider. No external dependencies."""

    name = "allowlist"

    def __init__(self, *, allowed_tools: list[str] | None = None, denied_tools: list[str] | None = None):
        # Distinguish "no allowlist configured" (None -> allow all) from an
        # explicitly empty allowlist ([] -> allow nothing). A truthiness test
        # would collapse [] into None and fail open, letting every tool through
        # when the operator intended to permit none.
        "实现 __init__ 协议方法，保持对象交互语义一致"
        self._allowed = set(allowed_tools) if allowed_tools is not None else None
        self._denied = set(denied_tools) if denied_tools else set()

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        "执行 evaluate 的明确职责，并返回与调用约定一致的结果"
        if self._allowed is not None and request.tool_name not in self._allowed:
            return GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.tool_not_allowed", message=f"tool '{request.tool_name}' not in allowlist")])
        if request.tool_name in self._denied:
            return GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.tool_not_allowed", message=f"tool '{request.tool_name}' is denied")])
        return GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.allowed")])

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        "执行 aevaluate 的明确职责，并返回与调用约定一致的结果"
        return self.evaluate(request)
