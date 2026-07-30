"""通过 Socket Mode 接入 Slack 通道，无需暴露公网 HTTP 回调地址。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from markdown_to_mrkdwn import SlackMarkdownConverter

from app.channels.base import Channel
from app.channels.commands import is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

_slack_md_converter = SlackMarkdownConverter()


def _normalize_allowed_users(allowed_users: Any) -> set[str]:
    """将允许用户配置统一为非空 Slack 用户 ID 集合，并兼容单个标量值。"""
    if allowed_users is None:
        return set()
    if isinstance(allowed_users, str):
        values = [allowed_users]
    elif isinstance(allowed_users, list | tuple | set):
        values = allowed_users
    else:
        logger.warning(
            "Slack allowed_users should be a list of Slack user IDs or a single Slack user ID string; treating %s as one string value",
            type(allowed_users).__name__,
        )
        values = [allowed_users]
    return {str(user_id) for user_id in values if str(user_id)}


def _strip_leading_slack_bot_mention(text: str, bot_user_id: str | None) -> str:
    """仅在文本开头提及当前机器人时删除该 Slack 提及标记。"""
    if not bot_user_id:
        return text
    if not text.startswith("<@"):
        return text
    end = text.find(">")
    if end <= 2:
        return text
    mentioned_user_id = text[2:end].split("|", 1)[0].lstrip("!")
    if mentioned_user_id != bot_user_id:
        return text
    return text[end + 1 :].lstrip()


class SlackChannel(Channel):
    """使用 Socket Mode 的 Slack 即时消息通道。

    ``bot_token`` 为机器人 OAuth 令牌，``app_token`` 为 Socket Mode 应用令牌；
    ``allowed_users`` 可为 Slack 用户 ID 列表或单个 ID，空值表示不限制用户。
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        """初始化 Socket 客户端、用户白名单、机器人身份和按连接缓存的 WebClient。"""
        super().__init__(name="slack", bus=bus, config=config)
        self._socket_client = None
        self._web_client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._allowed_users = _normalize_allowed_users(config.get("allowed_users", []))
        self._web_client_factory = config.get("web_client_factory")
        self._connection_web_clients: dict[str, tuple[str, Any]] = {}
        configured_bot_user_id = config.get("bot_user_id")
        self._bot_user_id = str(configured_bot_user_id).lstrip("@") if configured_bot_user_id else None

    async def start(self) -> None:
        """校验令牌并启动 Slack Socket Mode，在后台线程维持 SDK 连接。"""
        if self._running:
            return

        try:
            from slack_sdk import WebClient
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.response import SocketModeResponse
        except ImportError:
            logger.error("slack-sdk is not installed. Install it with: uv add slack-sdk")
            return

        self._SocketModeResponse = SocketModeResponse
        if self._web_client_factory is None:
            self._web_client_factory = WebClient

        bot_token = self.config.get("bot_token", "")
        app_token = self.config.get("app_token", "")

        if self.config.get("event_delivery") == "http":
            logger.error("Slack HTTP Events mode is not supported by this channel adapter; use Socket Mode with app_token")
            return

        if not bot_token or not app_token:
            logger.error("Slack channel requires bot_token and app_token")
            return

        await self._initialize_operator_web_client(str(bot_token))
        self._socket_client = SocketModeClient(
            app_token=app_token,
            web_client=self._web_client,
        )
        self._loop = asyncio.get_event_loop()

        self._socket_client.socket_mode_request_listeners.append(self._on_socket_event)

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # Socket Mode 的阻塞连接在后台执行器中运行。
        asyncio.get_event_loop().run_in_executor(None, self._socket_client.connect)
        logger.info("Slack channel started")

    async def stop(self) -> None:
        """取消总线订阅并关闭 Socket Mode 客户端。"""
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._socket_client:
            self._socket_client.close()
            self._socket_client = None
        logger.info("Slack channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        """在 ``thread_ts`` 指定的 Slack 线程中发送文本，并按策略重试失败请求。"""
        web_client = await self._get_web_client_for_message(msg)
        if not web_client:
            return

        kwargs: dict[str, Any] = {
            "channel": msg.chat_id,
            "text": _slack_md_converter.convert(msg.text),
        }
        if msg.thread_ts:
            kwargs["thread_ts"] = msg.thread_ts

        async def post_message() -> None:
            """在线程池调用 Slack API，成功后为回复线程根消息添加完成标记。"""
            await asyncio.to_thread(web_client.chat_postMessage, **kwargs)
            # 为线程根消息添加完成反应。
            if msg.thread_ts:
                await asyncio.to_thread(
                    self._add_reaction_with_client,
                    web_client,
                    msg.chat_id,
                    msg.thread_ts,
                    "white_check_mark",
                )

        try:
            await self._send_with_retry(
                post_message,
                max_retries=_max_retries,
                log_prefix="[Slack]",
            )
        except Exception:
            # 发送失败时为线程根消息添加失败反应。
            if msg.thread_ts:
                try:
                    await asyncio.to_thread(
                        self._add_reaction_with_client,
                        web_client,
                        msg.chat_id,
                        msg.thread_ts,
                        "x",
                    )
                except Exception:
                    pass
            raise

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """将附件上传至 Slack 频道，并在存在 ``thread_ts`` 时归入对应回复线程。"""
        web_client = await self._get_web_client_for_message(msg)
        if not web_client:
            return False

        try:
            kwargs: dict[str, Any] = {
                "channel": msg.chat_id,
                "file": str(attachment.actual_path),
                "filename": attachment.filename,
                "title": attachment.filename,
            }
            if msg.thread_ts:
                kwargs["thread_ts"] = msg.thread_ts

            await asyncio.to_thread(web_client.files_upload_v2, **kwargs)
            logger.info("[Slack] file uploaded: %s to channel=%s", attachment.filename, msg.chat_id)
            return True
        except Exception:
            logger.exception("[Slack] failed to upload file: %s", attachment.filename)
            return False

    # 以下为 Slack SDK 事件与连接身份处理的内部辅助方法。

    async def _initialize_operator_web_client(self, bot_token: str) -> None:
        """创建运营机器人 WebClient，并在未配置时通过 ``auth_test`` 获取机器人 ID。"""
        self._web_client = self._web_client_factory(token=bot_token)
        if self._bot_user_id is not None:
            return
        try:
            auth_info = await asyncio.to_thread(self._web_client.auth_test)
            user_id = auth_info.get("user_id") if isinstance(auth_info, dict) else None
            if user_id is None:
                auth_get = getattr(auth_info, "get", None)
                user_id = auth_get("user_id") if callable(auth_get) else None
            if isinstance(user_id, str) and user_id:
                self._bot_user_id = user_id
        except Exception:
            logger.warning("[Slack] failed to resolve bot user id; app mention text may include the bot mention", exc_info=True)

    async def _get_web_client_for_message(self, msg: OutboundMessage):
        """返回消息所属连接的 WebClient；令牌不变时复用其会话和限流状态。"""
        if msg.connection_id and self._connection_repo is not None:
            credentials = await self._connection_repo.get_credentials(msg.connection_id)
            access_token = credentials.get("access_token") if credentials else None
            if not access_token:
                return self._web_client
            # WebClient 自带 HTTP 会话和限流状态，因此同一连接在令牌不变时复用实例。
            cached = self._connection_web_clients.get(msg.connection_id)
            if cached is not None and cached[0] == access_token:
                return cached[1]
            if self._web_client_factory is None:
                from slack_sdk import WebClient

                self._web_client_factory = WebClient
            web_client = self._web_client_factory(token=access_token)
            self._connection_web_clients[msg.connection_id] = (access_token, web_client)
            return web_client
        return self._web_client

    @staticmethod
    def _add_reaction_with_client(web_client, channel_id: str, timestamp: str, emoji: str) -> None:
        """使用指定客户端添加表情反应；重复反应视为正常结果。"""
        try:
            web_client.reactions_add(
                channel=channel_id,
                timestamp=timestamp,
                name=emoji,
            )
        except Exception as exc:
            if "already_reacted" not in str(exc):
                logger.warning("[Slack] failed to add reaction %s: %s", emoji, exc)

    def _add_reaction(self, channel_id: str, timestamp: str, emoji: str) -> None:
        """使用运营机器人尽力为消息添加表情反应，不影响主流程。"""
        if not self._web_client:
            return
        self._add_reaction_with_client(self._web_client, channel_id, timestamp, emoji)

    def _send_running_reply(self, channel_id: str, thread_ts: str) -> None:
        """从 SDK 线程向回复线程发送处理中提示，作为流式响应的可见起点。"""
        if not self._web_client:
            return
        try:
            self._web_client.chat_postMessage(
                channel=channel_id,
                text=":hourglass_flowing_sand: Working on it...",
                thread_ts=thread_ts,
            )
            logger.info("[Slack] 'Working on it...' reply sent in channel=%s, thread_ts=%s", channel_id, thread_ts)
        except Exception:
            logger.exception("[Slack] failed to send running reply in channel=%s", channel_id)

    def _on_socket_event(self, client, req) -> None:
        """处理每个 Slack Socket Mode 事件：先确认收包，再分派消息或提及事件。"""
        try:
            # 立即确认事件，避免 Slack 重投递。
            response = self._SocketModeResponse(envelope_id=req.envelope_id)
            client.send_socket_mode_response(response)

            event_type = req.type
            if event_type != "events_api":
                return

            if self._bot_user_id is None:
                authorization = next((item for item in req.payload.get("authorizations", []) if isinstance(item, dict)), None)
                user_id = authorization.get("user_id") if authorization else None
                if isinstance(user_id, str) and user_id:
                    self._bot_user_id = user_id

            event = req.payload.get("event", {})
            etype = event.get("type", "")

            # 处理私信与机器人提及消息事件。
            if etype in ("message", "app_mention"):
                self._handle_message_event(
                    event,
                    team_id=req.payload.get("team_id") or req.payload.get("team") or event.get("team"),
                )

        except Exception:
            logger.exception("Error processing Slack event")

    def _handle_message_event(self, event: dict, *, team_id: str | None = None) -> None:
        """过滤 Slack 事件、构造线程话题键，并转交主循环发布入站消息。"""
        # 忽略机器人消息和子类型事件，避免自触发循环。
        if event.get("bot_id") or event.get("subtype"):
            return

        user_id = event.get("user", "")

        text = event.get("text", "").strip()
        if event.get("type") == "app_mention":
            text = _strip_leading_slack_bot_mention(text, self._bot_user_id)
        if not text:
            return

        connect_code = self._pending_connect_code(text)
        if connect_code:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._bind_connection_from_connect_code(
                        event=event,
                        team_id=str(team_id or ""),
                        code=connect_code,
                    ),
                    self._loop,
                )
            return

        # 连接码先于用户白名单处理，使浏览器发起的绑定可建立新的外部身份。
        if self._allowed_users and user_id not in self._allowed_users:
            logger.debug("Ignoring message from non-allowed user: %s", user_id)
            return

        channel_id = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts", "")

        if is_known_channel_command(text):
            msg_type = InboundMessageType.COMMAND
        else:
            msg_type = InboundMessageType.CHAT

        # ``topic_id`` 使用 ``thread_ts``：线程消息共享根消息时间戳；非线程消息
        # 使用自身时间戳，因此各自创建独立的 DeerFlow 话题键。
        inbound = self._make_inbound(
            chat_id=channel_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            thread_ts=thread_ts,
            metadata={
                # 调用方已按载荷 team_id/team、再按事件 team 的顺序解析团队 ID。
                "team_id": team_id,
                "message_id": event.get("ts"),
                "client_msg_id": event.get("client_msg_id"),
            },
        )
        inbound.topic_id = thread_ts

        if self._loop and self._loop.is_running():
            # 用眼睛反应确认已接收。
            self._add_reaction(channel_id, event.get("ts", thread_ts), "eyes")
            # 在 SDK 线程先发送处理中提示，不等待其完成。
            self._send_running_reply(channel_id, thread_ts)
            if self._connection_repo is None:
                asyncio.run_coroutine_threadsafe(self.bus.publish_inbound(inbound), self._loop)
            else:
                asyncio.run_coroutine_threadsafe(self._publish_inbound_with_connection(inbound, team_id=team_id), self._loop)

    async def _publish_inbound_with_connection(self, inbound, *, team_id: str | None = None) -> None:
        """附加 Slack 连接身份后，将入站消息发布到异步消息总线。"""
        inbound = await self._attach_connection_identity(inbound, team_id=team_id)
        await self.bus.publish_inbound(inbound)

    async def _attach_connection_identity(self, inbound, *, team_id: str | None = None):
        """以 Slack 团队 ID 作为工作区键，为入站消息解析已绑定的 DeerFlow 身份。"""
        workspace_id = str(team_id or inbound.metadata.get("team_id") or "")
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="slack",
            workspace_id=workspace_id,
        )

    async def _bind_connection_from_connect_code(self, *, event: dict, team_id: str, code: str) -> bool:
        """消费连接码，将 Slack 用户和团队绑定到拥有该码的 DeerFlow 用户。"""
        if self._connection_repo is None or not code:
            return False

        channel_id = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
        state = await self._connection_repo.consume_oauth_state(provider="slack", state=code)
        if state is None:
            await self._post_connection_reply(channel_id, "Slack connection code is invalid or expired.", thread_ts)
            return True

        user_id = str(event.get("user") or "")
        if not user_id or not team_id:
            await self._post_connection_reply(channel_id, "Slack connection could not be completed from this message.", thread_ts)
            return True

        await self._connection_repo.upsert_connection(
            owner_user_id=state["owner_user_id"],
            provider="slack",
            external_account_id=user_id,
            workspace_id=team_id,
            metadata={
                "team_id": team_id,
                "channel_id": channel_id,
            },
            status="connected",
        )
        await self._post_connection_reply(channel_id, "Slack connected to DeerFlow.", thread_ts)
        return True

    async def _post_connection_reply(self, channel_id: str, text: str, thread_ts: str | None = None) -> None:
        """向连接码来源的 Slack 频道或线程发送绑定结果。"""
        if not self._web_client or not channel_id:
            return
        kwargs: dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        try:
            await asyncio.to_thread(self._web_client.chat_postMessage, **kwargs)
        except Exception:
            logger.exception("[Slack] failed to send connection reply in channel=%s", channel_id)
