'未说明'

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Principal:
    '未说明principal未说明'

    user_id: str | None = None
    role: str | None = None
    oauth_provider: str | None = None
    oauth_id: str | None = None
    channel_user_id: str | None = None
    is_internal: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthzRequest:
    '未说明'

    principal: Principal
    resource: str
    """Resource type, e.g. ``"tool"``, ``"model"``, ``"skill"``, ``"sandbox"``, ``"mcp_server"``, ``"route"``."""

    action: str
    """Action on the resource, e.g. ``"call"``, ``"list"``, ``"use"``, ``"activate"``, ``"execute"``, ``"read"``, ``"write"``."""

    target: str
    """Resource identifier: tool name, model name, skill name, ``"route:threads:read"``, etc."""

    context: dict[str, Any] = field(default_factory=dict)
    """Additional context: ``thread_id``, ``run_id``, ``tool_call_id``, ``tool_input``, ``is_subagent``, etc."""


@dataclass
class AuthzReason:
    '未说明reason未说明'

    code: str
    message: str = ""


@dataclass
class AuthzDecision:
    '未说明decision未说明'

    allow: bool
    reasons: list[AuthzReason] = field(default_factory=list)
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AuthorizationProvider(Protocol):
    '未说明authorization未说明'

    name: str

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        '未说明authorize未说明'
        ...

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        '未说明aauthorize未说明'
        ...

    def filter_resources(
        self,
        principal: Principal,
        resource_type: str,
        candidates: list[str],
    ) -> list[str]:
        '未说明filter?resources未说明'
        ...
