'''维护按即时通讯通道划分的 Agent 运行策略。

策略注册表与 ``ChannelRunPolicy`` 独立于管理器定义，使通道能够在导入时注册能力，
又不会与 :mod:`app.channels.manager` 形成循环依赖。``ChannelManager`` 在
``_resolve_run_params`` 之后按 ``msg.channel_name`` 应用对应策略。
'''

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.channels.message_bus import InboundMessage


@dataclass(frozen=True, slots=True)
class ChannelRunPolicy:
    '''描述 :meth:`ChannelManager._apply_channel_policy` 应用的通道差异。

    普通交互式通道采用保守默认值；Webhook 驱动的自治通道则可集中声明更高递归
    上限、禁止同步澄清、动态凭据、身份门禁例外或无需等待最终回复等能力。把这些
    差异收敛为不可变数据，新增通道时只需注册策略，不必在管理器多个分支中硬编码。

    ``is_interactive`` 为假时，管理器通过
    ``run_context["disable_clarification"]`` 阻止无人值守任务等待人工回复。
    ``default_recursion_limit`` 只提高现有上限，不会压低调用方的显式配置。
    ``credentials_provider`` 可在运行前注入短期平台凭据，其失败会降级为只读执行。
    ``requires_bound_identity`` 允许已在 Webhook 边界完成 HMAC 验证的通道跳过
    ``/connect`` 身份流程。``fire_and_forget`` 使用 ``runs.create``，适合自行回写
    平台且可能超过 SDK 等待超时的任务。``serialize_thread_runs`` 则只串行化同一
    DeerFlow 线程，避免快速连续消息触发运行冲突，同时保留不同线程之间的并发。
    '''

    is_interactive: bool = True
    default_recursion_limit: int | None = None
    credentials_provider: Callable[[InboundMessage, dict[str, Any]], Awaitable[None]] | None = None
    requires_bound_identity: bool = True
    fire_and_forget: bool = False
    serialize_thread_runs: bool = False


# 未注册通道沿用交互式安全默认值；Webhook 通道在模块导入时显式登记例外策略。
CHANNEL_RUN_POLICY: dict[str, ChannelRunPolicy] = {}
