'''定义工具调用授权时传递的请求、决策数据结构及策略提供方契约。'''

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GuardrailRequest:
    '''携带待授权工具调用及其用户、线程、运行和身份提供方上下文。'''

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
    '''描述授权允许或拒绝的原因代码及面向调用方的说明。'''

    code: str
    message: str = ""


@dataclass
class GuardrailDecision:
    '''保存授权结论、原因、策略标识及提供方附带的元数据。'''

    allow: bool
    reasons: list[GuardrailReason] = field(default_factory=list)
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GuardrailProvider(Protocol):
    '''工具调用授权策略提供方的结构化接口，无需继承即可实现。

    配置通过类路径动态加载，运行时先尝试同步/异步对应的授权入口。
    '''

    name: str

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '''同步判断本次工具调用是否可以继续执行。'''
        ...

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        '''异步判断本次工具调用是否可以继续执行。'''
        ...
