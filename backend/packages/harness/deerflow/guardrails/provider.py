"""定义 provider 模块提供的职责与可复用接口。

GuardrailProvider protocol and data structures for pre-tool-call authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GuardrailRequest:
    """封装 GuardrailRequest 的状态、协作关系与公开操作。

    Context passed to the provider for each tool call."""

    tool_name: str
    tool_input: dict[str, Any]
    agent_id: str | None = None
    thread_id: str | None = None
    is_subagent: bool = False
    timestamp: str = ""
    user_id: str | None = None
    user_role: str | None = None
    oauth_provider: str | None = None
    oauth_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None


@dataclass
class GuardrailReason:
    """封装 GuardrailReason 的状态、协作关系与公开操作。

    Structured reason for an allow/deny decision (OAP reason object)."""

    code: str
    message: str = ""


@dataclass
class GuardrailDecision:
    """封装 GuardrailDecision 的状态、协作关系与公开操作。

    Provider's allow/deny verdict (aligned with OAP Decision object)."""

    allow: bool
    reasons: list[GuardrailReason] = field(default_factory=list)
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GuardrailProvider(Protocol):
    """封装 GuardrailProvider 的状态、协作关系与公开操作。

    Contract for pluggable tool-call authorization.

        Any class with these methods works - no base class required.
        Providers are loaded by class path via resolve_variable(),
        the same mechanism DeerFlow uses for models, tools, and sandbox.
    """

    name: str

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """执行 evaluate 的明确职责，并返回与调用约定一致的结果。

        Evaluate whether a tool call should proceed."""
        ...

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """执行 aevaluate 的明确职责，并返回与调用约定一致的结果。

        Async variant."""
        ...
