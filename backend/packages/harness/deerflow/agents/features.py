"""定义代理运行时功能开关与中间件定位装饰器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from deerflow.config.memory_config import MemoryConfig


@dataclass
class RuntimeFeatures:
    """描述 ``create_deerflow_agent`` 可按需启用的内置能力。

    每个中间件功能可设为布尔值使用默认实现，或传入中间件实例完成替换；
    记忆配置供直接创建代理的调用方显式覆盖默认配置。
    """

    sandbox: bool | AgentMiddleware = True
    memory: bool | AgentMiddleware = False
    # Explicit memory config for direct create_deerflow_agent(features=...) callers.
    # The lead-agent AppConfig path passes resolved_app_config.memory directly.
    memory_config: MemoryConfig | None = None
    summarization: Literal[False] | AgentMiddleware = False
    subagent: bool | AgentMiddleware = False
    vision: bool | AgentMiddleware = False
    auto_title: bool | AgentMiddleware = False
    guardrail: Literal[False] | AgentMiddleware = False
    loop_detection: bool | AgentMiddleware = True
    token_budget: bool | AgentMiddleware = False


# ---------------------------------------------------------------------------
# Middleware positioning decorators
# ---------------------------------------------------------------------------


def Next(anchor: type[AgentMiddleware]):
    """标记自定义中间件应紧随指定锚点中间件之后插入。

    仅接受 ``AgentMiddleware`` 子类作为锚点，并把锚点类型记录在被装饰类上，
    供代理工厂组装额外中间件时解析。
    """
    if not (isinstance(anchor, type) and issubclass(anchor, AgentMiddleware)):
        raise TypeError(f"@Next expects an AgentMiddleware subclass, got {anchor!r}")

    def decorator(cls: type[AgentMiddleware]) -> type[AgentMiddleware]:
        """把后置锚点元数据写入被装饰的中间件类并返回该类。"""
        cls._next_anchor = anchor  # type: ignore[attr-defined]
        return cls

    return decorator


def Prev(anchor: type[AgentMiddleware]):
    """标记自定义中间件应紧邻指定锚点中间件之前插入。

    仅接受 ``AgentMiddleware`` 子类作为锚点，并把锚点类型记录在被装饰类上，
    供代理工厂组装额外中间件时解析。
    """
    if not (isinstance(anchor, type) and issubclass(anchor, AgentMiddleware)):
        raise TypeError(f"@Prev expects an AgentMiddleware subclass, got {anchor!r}")

    def decorator(cls: type[AgentMiddleware]) -> type[AgentMiddleware]:
        """把前置锚点元数据写入被装饰的中间件类并返回该类。"""
        cls._prev_anchor = anchor  # type: ignore[attr-defined]
        return cls

    return decorator
