"""提供由 Webhook 驱动的 GitHub PR/Issue 评论通道。

GitHub 不使用长轮询或 WebSocket，而是通过 HTTP Webhook 主动推送事件。入站消息由
``POST /api/webhooks/github`` 路由发布到消息总线，因此 ``start``/``stop`` 只管理
出站订阅，不创建平台监听器。

该通道不会自动发布 Agent 最终回答。coder、reviewer 等 Agent 在沙箱内使用 ``gh``
自行决定是否以及何时回写 Issue/PR；最终 assistant 消息只写入 ``gateway.log``。

只记录而不自动发布有三个原因：

- 同一事件可能同时绑定多个 Agent，自动发布会制造无意义的重复回复。
- Agent 往往需要在运行中发布 PR 链接等中间进度，单一最终消息无法表达该流程。
- 分发器的 ``_is_self_event`` 门禁已阻止 Agent 自己发布的评论回环触发同一 Agent。
"""

from __future__ import annotations

import logging
from typing import Any

from app.channels.base import Channel
from app.channels.message_bus import MessageBus, OutboundMessage

logger = logging.getLogger(__name__)


class GitHubChannel(Channel):
    """把 GitHub Webhook 入站事件接入共享消息总线。

    入站由 Webhook 路由发布，出站 ``send`` 仅记录日志，平台回写由沙箱中的 ``gh``
    完成。``channels.github.enabled`` 控制是否激活；``default_mention_login`` 在
    Agent 绑定未指定账号时为 ``require_mention`` 提供默认机器人名称。
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        """以固定通道名初始化 GitHub 适配器。"""
        super().__init__(name="github", bus=bus, config=config)

    # -- 生命周期 ----------------------------------------------------------

    async def start(self) -> None:
        """注册只记录日志的出站回调。

        GitHub 入站由 Webhook 推送，不需要长轮询或套接字监听器。
        """
        if self._running:
            return
        self.bus.subscribe_outbound(self._on_outbound)
        self._running = True
        logger.info("GitHubChannel started (webhook-driven, no polling)")

    async def stop(self) -> None:
        """注销出站回调。"""
        if not self._running:
            return
        self.bus.unsubscribe_outbound(self._on_outbound)
        self._running = False
        logger.info("GitHubChannel stopped")

    # -- 出站消息 ----------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """记录 Agent 最终消息，但不将其发布到 GitHub。

        ``github`` 元数据中的 ``repo``、``number`` 和 ``installation_id`` 只用于
        日志关联；缺少 ``repo`` 时回退到 ``chat_id``。
        """
        gh = msg.metadata.get("github", {}) if isinstance(msg.metadata, dict) else {}
        if not isinstance(gh, dict):
            gh = {}

        repo = gh.get("repo") or msg.chat_id
        number = gh.get("number")

        body = msg.text or ""

        logger.info(
            "[GitHubChannel] final message from agent for %s#%s (text_len=%d) — not posted; agents use `gh` directly",
            repo,
            number,
            len(body),
        )
        # 正文放在 DEBUG 级别并截断，既便于关联运行，又不会淹没 INFO 日志。
        if body:
            logger.debug("[GitHubChannel] final body (truncated to 2000 chars): %s", body[:2000])
