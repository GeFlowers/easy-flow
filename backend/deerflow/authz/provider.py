'''定义授权主体、请求与决策的数据结构，以及同步和异步授权提供方的协议。'''

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Principal:
    '''记录发起操作的用户身份、来源标识、内部用户标记及扩展属性。'''

    user_id: str | None = None
    role: str | None = None
    oauth_provider: str | None = None
    oauth_id: str | None = None
    channel_user_id: str | None = None
    is_internal: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthzRequest:
    '''描述一次待授权操作，包括主体、资源类别、动作、目标及调用上下文。'''

    principal: Principal
    resource: str
    '''授权对象的类别，例如工具、模型、技能、沙箱、消息服务或接口路由。'''

    action: str
    '''针对对象执行的动作，例如调用、查看列表、启用、执行、读取或写入。'''

    target: str
    '''具体授权目标的标识，例如工具名、模型名、技能名或线程读取路由。'''

    context: dict[str, Any] = field(default_factory=dict)
    '''随授权请求提供的调用上下文，例如线程、运行、工具调用及子代理信息。'''


@dataclass
class AuthzReason:
    '''说明授权决策中某项允许或拒绝理由的机器码和可读信息。'''

    code: str
    message: str = ""


@dataclass
class AuthzDecision:
    '''承载授权是否放行、判定理由、策略标识和附加元数据。'''

    allow: bool
    reasons: list[AuthzReason] = field(default_factory=list)
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AuthorizationProvider(Protocol):
    '''供授权实现遵循的接口；同时支持单次判定和按主体过滤资源列表。'''

    name: str

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        '''同步判定请求主体是否可以对目标资源执行指定动作。'''
        ...

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        '''异步判定请求主体是否可以对目标资源执行指定动作。'''
        ...

    def filter_resources(
        self,
        principal: Principal,
        resource_type: str,
        candidates: list[str],
    ) -> list[str]:
        '''从候选资源中筛出该主体有权访问的项目。'''
        ...
