"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.provider import (
    AuthorizationProvider,
    AuthzDecision,
    AuthzReason,
    AuthzRequest,
    Principal,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import (
    AuthorizationConfig,
    get_authorization_config,
    load_authorization_config_from_dict,
    reset_authorization_config,
)
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.guardrails.provider import GuardrailDecision, GuardrailProvider, GuardrailRequest

# --- 测试提供商 ---


class _AllowAllProvider:
    """归集“该项全部提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    name = "allow-all"

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return AuthzDecision(allow=True, reasons=[AuthzReason(code="test.allowed", message="allow-all")])

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return list(candidates)


class _DenyAllProvider:
    """归集“拒绝全部提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    name = "deny-all"

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return AuthzDecision(allow=False, reasons=[AuthzReason(code="test.denied", message="deny-all")], policy_id="test.deny.v1")

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return []


class _FilterByDenylistProvider:
    """归集“过滤该项该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    name = "denylist-filter"

    def __init__(self, *, denied: list[str] | None = None):
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._denied = set(denied) if denied else set()

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        if request.target in self._denied:
            return AuthzDecision(allow=False, reasons=[AuthzReason(code="test.denied", message=f"'{request.target}' is denied")])
        return AuthzDecision(allow=True, reasons=[AuthzReason(code="test.allowed")])

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return [c for c in candidates if c not in self._denied]


# --- 协议一致性 ---


class TestProtocolConformance:
    """归集“协议该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_allow_all_is_authorization_provider(self):
        """验证“该项全部该项授权提供方”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        assert isinstance(_AllowAllProvider(), AuthorizationProvider)

    def test_deny_all_is_authorization_provider(self):
        """验证“拒绝全部该项授权提供方”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        assert isinstance(_DenyAllProvider(), AuthorizationProvider)

    def test_plain_object_without_methods_is_not_provider(self):
        """验证“该项对象不使用该项该项该项提供方”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        class _NotAProvider:
            """归集“该项该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            pass

        assert not isinstance(_NotAProvider(), AuthorizationProvider)

    def test_provider_without_filter_resources_is_not_provider(self):
        """验证“提供方不使用过滤资源该项该项提供方”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""

        class _NoFilterMethod:
            """归集“该项过滤该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "no-filter"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return self.authorize(request)

        assert not isinstance(_NoFilterMethod(), AuthorizationProvider)


# --- 数据类构造 ---


class TestDataclasses:
    """归集“该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_principal_defaults(self):
        """验证“主体该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        p = Principal()
        assert p.user_id is None
        assert p.role is None
        assert p.oauth_provider is None
        assert p.oauth_id is None
        assert p.channel_user_id is None
        assert p.is_internal is False
        assert p.attributes == {}

    def test_principal_with_fields(self):
        """验证“主体使用字段”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        p = Principal(user_id="u1", role="admin", oauth_provider="github", oauth_id="gh-123", is_internal=True)
        assert p.user_id == "u1"
        assert p.role == "admin"
        assert p.oauth_provider == "github"
        assert p.oauth_id == "gh-123"
        assert p.is_internal is True

    def test_authz_request(self):
        """验证“该项请求”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        p = Principal(user_id="u1", role="user")
        req = AuthzRequest(principal=p, resource="tool", action="call", target="bash")
        assert req.principal.user_id == "u1"
        assert req.resource == "tool"
        assert req.action == "call"
        assert req.target == "bash"
        assert req.context == {}

    def test_authz_request_with_context(self):
        """验证“该项请求使用上下文”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        p = Principal(user_id="u1")
        req = AuthzRequest(principal=p, resource="tool", action="call", target="write_file", context={"thread_id": "t1"})
        assert req.context["thread_id"] == "t1"

    def test_authz_decision_defaults(self):
        """验证“该项决策该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        d = AuthzDecision(allow=True)
        assert d.allow is True
        assert d.reasons == []
        assert d.policy_id is None
        assert d.metadata == {}

    def test_authz_decision_with_reasons(self):
        """验证“该项决策使用该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        d = AuthzDecision(allow=False, reasons=[AuthzReason(code="denied", message="no access")], policy_id="p1")
        assert d.allow is False
        assert len(d.reasons) == 1
        assert d.reasons[0].code == "denied"
        assert d.reasons[0].message == "no access"
        assert d.policy_id == "p1"


# --- 过滤资源 ---


class TestFilterResources:
    """归集“过滤资源”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_allow_all_returns_all(self):
        """验证“该项全部返回全部”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        provider = _AllowAllProvider()
        result = provider.filter_resources(Principal(role="user"), "tool", ["bash", "web_search", "read_file"])
        assert result == ["bash", "web_search", "read_file"]

    def test_deny_all_returns_empty(self):
        """验证“拒绝全部返回空值”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        provider = _DenyAllProvider()
        result = provider.filter_resources(Principal(role="user"), "tool", ["bash", "web_search"])
        assert result == []

    def test_denylist_filter_removes_denied(self):
        """验证“该项过滤该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        provider = _FilterByDenylistProvider(denied=["bash", "write_file"])
        result = provider.filter_resources(Principal(role="user"), "tool", ["bash", "web_search", "write_file", "read_file"])
        assert result == ["web_search", "read_file"]


# 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。


def _make_guardrail_request(
    *,
    tool_name: str = "bash",
    tool_input: dict | None = None,
    user_id: str | None = "u1",
    user_role: str | None = "user",
    thread_id: str | None = "t1",
    is_subagent: bool = False,
    agent_id: str | None = None,
    timestamp: str = "",
) -> GuardrailRequest:
    """为“构造该项请求”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    return GuardrailRequest(
        tool_name=tool_name,
        tool_input=tool_input or {},
        user_id=user_id,
        user_role=user_role,
        thread_id=thread_id,
        is_subagent=is_subagent,
        agent_id=agent_id,
        timestamp=timestamp,
    )


class TestGuardrailAuthorizationAdapter:
    """归集“该项授权适配器”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def test_adapter_name(self):
        """验证“适配器名称”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        assert adapter.name == "authorization"

    def test_adapter_is_guardrail_provider(self):
        """验证“适配器该项该项提供方”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        assert isinstance(adapter, GuardrailProvider)

    def test_evaluate_allow(self):
        """验证“评估该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        gr_req = _make_guardrail_request(tool_name="web_search")
        decision = adapter.evaluate(gr_req)
        assert decision.allow is True
        assert len(decision.reasons) == 1
        assert decision.reasons[0].code == "test.allowed"

    def test_evaluate_deny(self):
        """验证“评估拒绝”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        adapter = GuardrailAuthorizationAdapter(_DenyAllProvider())
        gr_req = _make_guardrail_request(tool_name="bash")
        decision = adapter.evaluate(gr_req)
        assert decision.allow is False
        assert decision.policy_id == "test.deny.v1"

    def test_evaluate_maps_principal_identity(self):
        """验证“评估该项主体身份”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            """归集“该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                captured.append(request)
                return AuthzDecision(allow=True, reasons=[AuthzReason(code="ok")])

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider())
        gr_req = _make_guardrail_request(user_id="user-42", user_role="admin", tool_name="write_file")
        adapter.evaluate(gr_req)

        assert len(captured) == 1
        authz_req = captured[0]
        assert authz_req.principal.user_id == "user-42"
        assert authz_req.principal.role == "admin"
        assert authz_req.resource == "tool"
        assert authz_req.action == "call"
        assert authz_req.target == "write_file"

    def test_evaluate_does_not_populate_is_internal_in_phase0(self):
        """验证“评估该项该项该项该项内部该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            """归集“该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                captured.append(request)
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider())
        adapter.evaluate(_make_guardrail_request(user_role="user"))

        # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        assert captured[0].principal.is_internal is False

    def test_evaluate_maps_context_fields(self):
        """验证“评估该项上下文字段”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            """归集“该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                captured.append(request)
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider())
        gr_req = _make_guardrail_request(
            tool_name="write_file",
            tool_input={"path": "/tmp/test.txt"},
            thread_id="thread-99",
            is_subagent=True,
            agent_id="passport-42",
            timestamp="2026-07-13T00:00:00Z",
        )
        adapter.evaluate(gr_req)

        ctx = captured[0].context
        assert ctx["thread_id"] == "thread-99"
        assert ctx["tool_input"] == {"path": "/tmp/test.txt"}
        assert ctx["is_subagent"] is True
        assert ctx["agent_id"] == "passport-42"
        assert ctx["timestamp"] == "2026-07-13T00:00:00Z"

    def test_custom_resource_type_and_action(self):
        """验证“该项该项类型该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            """归集“该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                captured.append(request)
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider(), resource_type="model", action="use")
        adapter.evaluate(_make_guardrail_request(tool_name="claude-sonnet-4-6"))

        assert captured[0].resource == "model"
        assert captured[0].action == "use"

    def test_aevaluate_allow(self):
        """验证“该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        gr_req = _make_guardrail_request(tool_name="web_search")
        decision = asyncio.run(adapter.aevaluate(gr_req))
        assert decision.allow is True

    def test_aevaluate_deny(self):
        """验证“该项拒绝”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        adapter = GuardrailAuthorizationAdapter(_DenyAllProvider())
        gr_req = _make_guardrail_request(tool_name="bash")
        decision = asyncio.run(adapter.aevaluate(gr_req))
        assert decision.allow is False

    def test_decision_conversion_preserves_metadata(self):
        """验证“决策该项保留元数据”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        class _MetadataProvider:
            """归集“元数据提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "metadata"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return AuthzDecision(
                    allow=True,
                    reasons=[AuthzReason(code="ok", message="allowed by policy X")],
                    policy_id="rbac.v1",
                    metadata={"rule_id": "rule-42"},
                )

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_MetadataProvider())
        decision = adapter.evaluate(_make_guardrail_request())

        assert isinstance(decision, GuardrailDecision)
        assert decision.policy_id == "rbac.v1"
        assert decision.metadata == {"rule_id": "rule-42"}
        assert decision.reasons[0].message == "allowed by policy X"

    def test_evaluate_propagates_provider_exception(self):
        """验证“评估该项提供方异常”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""

        class _ExplodingProvider:
            """归集“该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "exploding"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                raise RuntimeError("provider crashed")

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                raise RuntimeError("provider crashed")

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_ExplodingProvider())
        with pytest.raises(RuntimeError, match="provider crashed"):
            adapter.evaluate(_make_guardrail_request())

    def test_aevaluate_propagates_provider_exception(self):
        """验证“该项该项提供方异常”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""

        class _ExplodingProvider:
            """归集“该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
            name = "exploding"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                raise RuntimeError("provider crashed")

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                raise RuntimeError("provider crashed")

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                """为“过滤资源”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_ExplodingProvider())
        with pytest.raises(RuntimeError, match="provider crashed"):
            asyncio.run(adapter.aevaluate(_make_guardrail_request()))


# --- 配置 ---


class TestAuthorizationConfig:
    """归集“授权配置”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""

    def teardown_method(self):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        reset_authorization_config()

    def test_defaults(self):
        """验证“该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        config = AuthorizationConfig()
        assert config.enabled is False
        assert config.fail_closed is True
        assert config.default_role == "user"
        assert config.provider is None

    def test_get_returns_defaults_when_not_loaded(self):
        """验证“获取返回该项当该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        reset_authorization_config()
        config = get_authorization_config()
        assert config.enabled is False

    def test_load_from_dict(self):
        """验证“加载该项字典”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        config = load_authorization_config_from_dict(
            {
                "enabled": True,
                "default_role": "guest",
                "provider": {
                    "use": "my_package:MyProvider",
                    "config": {"roles": {"admin": {}}},
                },
            }
        )
        assert config.enabled is True
        assert config.default_role == "guest"
        assert config.provider is not None
        assert config.provider.use == "my_package:MyProvider"
        assert config.provider.config == {"roles": {"admin": {}}}

    def test_singleton_persistence(self):
        """验证“单例持久化”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        load_authorization_config_from_dict({"enabled": True})
        config2 = get_authorization_config()
        assert config2.enabled is True

    def test_reset_clears_singleton(self):
        """验证“重置清除单例”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        load_authorization_config_from_dict({"enabled": True})
        reset_authorization_config()
        config = get_authorization_config()
        assert config.enabled is False

    def test_app_config_has_authorization_field(self):
        """验证“应用配置该项授权该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        app_config = AppConfig(sandbox=SandboxConfig(use="test"))
        assert hasattr(app_config, "authorization")
        assert app_config.authorization.enabled is False
        assert app_config.authorization.fail_closed is True
        assert app_config.authorization.default_role == "user"

    def test_app_config_load_propagates_to_singleton(self):
        """验证“应用配置加载该项该项单例”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
        reset_authorization_config()
        validated = AppConfig.model_validate(
            {
                "sandbox": {"use": "test"},
                "authorization": {
                    "enabled": True,
                    "default_role": "operator",
                },
            }
        )
        # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
        AppConfig._apply_singleton_configs(validated, acp_agents={})

        singleton = get_authorization_config()
        assert singleton.enabled is True
        assert singleton.default_role == "operator"
