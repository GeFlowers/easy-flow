"""通过 discord.py 接入 Discord 消息通道，并维护频道与会话线程的路由关系。"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.channels.base import Channel
from app.channels.commands import is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

_DISCORD_MAX_MESSAGE_LEN = 2000


class DiscordChannel(Channel):
    """Discord 机器人通道。

    ``channels.discord`` 配置中的 ``bot_token`` 是机器人令牌；``allowed_guilds``
    限制可接收的服务器；``mention_only`` 仅在被提及时响应；``allowed_channels``
    是提及限制的例外频道；``thread_mode`` 决定是否为频道会话创建 Discord 线程，
    默认值与 ``mention_only`` 保持一致。
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        """初始化 Discord 配置、线程映射、输入状态任务和跨线程事件循环引用。"""
        super().__init__(name="discord", bus=bus, config=config)
        self._bot_token = str(config.get("bot_token", "")).strip()
        self._allowed_guilds: set[int] = set()
        for guild_id in config.get("allowed_guilds", []):
            try:
                self._allowed_guilds.add(int(guild_id))
            except (TypeError, ValueError):
                continue
        self._mention_only: bool = bool(config.get("mention_only", False))
        self._thread_mode: bool = config.get("thread_mode", self._mention_only)
        self._allowed_channels: set[str] = set()
        for channel_id in config.get("allowed_channels", []):
            self._allowed_channels.add(str(channel_id))

        # 记录频道 ID 到 Discord 线程 ID 的会话映射；内存副本会持久化为 JSON。
        # 该文件独立于 ChannelStore，后者负责 IM 会话到 DeerFlow 线程的另一层映射。
        self._active_threads: dict[str, str] = {}
        # 用于常数时间判断线程 ID 的反查集合，避免遍历映射值。
        self._active_thread_ids: set[str] = set()
        # 保护映射和 JSON 文件；Discord 循环线程与主线程都会读写它们。
        self._thread_store_lock = threading.Lock()
        store = config.get("channel_store")
        if store is not None:
            self._thread_store_path = store._path.parent / "discord_threads.json"
        else:
            self._thread_store_path = Path.home() / ".deer-flow" / "channels" / "discord_threads.json"

        # 按回复目标管理输入状态任务。
        self._typing_tasks: dict[str, asyncio.Task] = {}

        self._client = None
        self._thread: threading.Thread | None = None
        self._discord_loop: asyncio.AbstractEventLoop | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._discord_module = None

    async def start(self) -> None:
        """创建 Discord 客户端并在专用线程启动其事件循环，同时恢复线程映射。"""
        if self._running:
            return

        try:
            import discord
        except ImportError:
            logger.error("discord.py is not installed. Install it with: uv add discord.py")
            return

        if not self._bot_token:
            logger.error("Discord channel requires bot_token")
            return

        intents = discord.Intents.default()
        intents.messages = True
        intents.guilds = True
        intents.message_content = True

        client = discord.Client(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self._client = client
        self._discord_module = discord
        self._main_loop = asyncio.get_event_loop()

        @client.event
        async def on_message(message) -> None:
            """把 discord.py 的消息事件转交给通道实例处理。"""
            await self._on_message(message)

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        self._thread = threading.Thread(target=self._run_client, daemon=True)
        self._thread.start()
        await asyncio.to_thread(self._load_active_threads)
        logger.info("Discord channel started")

    def _load_active_threads(self) -> None:
        """启动时从专用 JSON 文件恢复频道到 Discord 线程的映射。"""
        with self._thread_store_lock:
            try:
                if not self._thread_store_path.exists():
                    logger.debug("[Discord] no thread mappings file at %s", self._thread_store_path)
                    return
                data = json.loads(self._thread_store_path.read_text())
                self._active_threads.clear()
                self._active_thread_ids.clear()
                for channel_id, thread_id in data.items():
                    self._active_threads[channel_id] = thread_id
                    self._active_thread_ids.add(thread_id)
                if self._active_threads:
                    logger.info("[Discord] restored %d thread mappings from %s", len(self._active_threads), self._thread_store_path)
            except Exception:
                logger.exception("[Discord] failed to load thread mappings")

    def _record_thread_mapping(self, channel_id: str, thread_id: str) -> None:
        """同步更新频道到 Discord 线程的内存映射及其反查集合。

        此操作没有 I/O，必须先在事件循环中完成，使新线程中的追发消息在持久化完成前
        立即可被识别；磁盘写入由 ``_persist_thread_mappings`` 异步卸载处理。
        """
        old_id = self._active_threads.get(channel_id)
        self._active_threads[channel_id] = thread_id
        if old_id:
            self._active_thread_ids.discard(old_id)
        self._active_thread_ids.add(thread_id)

    def _persist_thread_mappings(self) -> None:
        """将当前线程映射写入磁盘，供 ``asyncio.to_thread`` 在线程池中调用。

        内存状态已由同步记录方法更新，持久化延迟不会影响入站消息路由；在锁内复制快照，
        防止并发记录在 JSON 序列化期间修改字典。
        """
        with self._thread_store_lock:
            try:
                snapshot = dict(self._active_threads)
                self._thread_store_path.parent.mkdir(parents=True, exist_ok=True)
                self._thread_store_path.write_text(json.dumps(snapshot, indent=2))
            except Exception:
                logger.exception("[Discord] failed to persist thread mappings")

    @staticmethod
    def _read_attachment_bytes(path: str) -> bytes:
        """同步读取附件字节，调用方应通过 ``asyncio.to_thread`` 避免阻塞事件循环。"""
        with open(path, "rb") as fp:
            return fp.read()

    async def stop(self) -> None:
        """取消输入状态、关闭 Discord 客户端并回收其专用线程。"""
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)

        # 取消全部仍在运行的输入状态任务。
        for target_id, task in list(self._typing_tasks.items()):
            if not task.done():
                task.cancel()
            logger.debug("[Discord] cancelled typing task for target %s", target_id)
        self._typing_tasks.clear()

        if self._client and self._discord_loop and self._discord_loop.is_running():
            close_future = asyncio.run_coroutine_threadsafe(self._client.close(), self._discord_loop)
            try:
                await asyncio.wait_for(asyncio.wrap_future(close_future), timeout=10)
            except TimeoutError:
                logger.warning("[Discord] client close timed out after 10s")
            except Exception:
                logger.exception("[Discord] error while closing client")

        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

        self._client = None
        self._discord_loop = None
        self._discord_module = None
        logger.info("Discord channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """向回复线程优先、频道兜底的目标发送文本，并在发送前停止输入状态。"""
        # 开始发送回复时停止对应目标的输入状态。
        stop_future = asyncio.run_coroutine_threadsafe(self._stop_typing(msg.chat_id, msg.thread_ts), self._discord_loop)
        await asyncio.wrap_future(stop_future)

        target = await self._resolve_target(msg)
        if target is None:
            logger.error("[Discord] target not found for chat_id=%s thread_ts=%s", msg.chat_id, msg.thread_ts)
            return

        text = msg.text or ""
        for chunk in self._split_text(text):
            send_future = asyncio.run_coroutine_threadsafe(target.send(chunk), self._discord_loop)
            await asyncio.wrap_future(send_future)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """向解析出的 Discord 线程或频道发送附件，并返回是否发送成功。"""
        stop_future = asyncio.run_coroutine_threadsafe(self._stop_typing(msg.chat_id, msg.thread_ts), self._discord_loop)
        await asyncio.wrap_future(stop_future)

        target = await self._resolve_target(msg)
        if target is None:
            logger.error("[Discord] target not found for file upload chat_id=%s thread_ts=%s", msg.chat_id, msg.thread_ts)
            return False

        if self._discord_module is None:
            return False

        try:
            # 在线程池读取会阻塞的文件 I/O，再把内存缓冲区交给 Discord 循环发送。
            # 发送 Future 结束后缓冲区即可回收，因此成功与失败路径都不会遗留文件句柄。
            data = await asyncio.to_thread(self._read_attachment_bytes, str(attachment.actual_path))
            file = self._discord_module.File(io.BytesIO(data), filename=attachment.filename)
            send_future = asyncio.run_coroutine_threadsafe(target.send(file=file), self._discord_loop)
            await asyncio.wrap_future(send_future)
            logger.info("[Discord] file uploaded: %s", attachment.filename)
            return True
        except Exception:
            logger.exception("[Discord] failed to upload file: %s", attachment.filename)
            return False

    async def _start_typing(self, channel, chat_id: str, thread_ts: str | None = None) -> None:
        """为线程优先、频道兜底的回复目标启动定期输入状态；同一目标最多一个任务。"""
        target_id = thread_ts or chat_id
        if target_id in self._typing_tasks:
            return  # 此回复目标已有输入状态任务。

        async def _typing_loop():
            """每十秒刷新一次 Discord 输入状态，直至任务被取消。"""
            try:
                while True:
                    try:
                        await channel.trigger_typing()
                    except Exception:
                        pass
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_typing_loop())
        self._typing_tasks[target_id] = task

    async def _stop_typing(self, chat_id: str, thread_ts: str | None = None) -> None:
        """停止指定线程或频道回复目标的输入状态任务。"""
        target_id = thread_ts or chat_id
        task = self._typing_tasks.pop(target_id, None)
        if task and not task.done():
            task.cancel()
            logger.debug("[Discord] stopped typing indicator for target %s", target_id)

    async def _add_reaction(self, message) -> None:
        """为已接收的消息添加勾选表情作为确认，失败不影响后续处理。"""
        try:
            await message.add_reaction("✅")
        except Exception:
            logger.debug("[Discord] failed to add reaction to message %s", message.id, exc_info=True)

    async def _on_message(self, message) -> None:
        """过滤并路由 Discord 入站消息，建立话题键、身份绑定和输入状态。"""
        if not self._running or not self._client:
            return

        if message.author.bot:
            return

        if self._client.user and message.author.id == self._client.user.id:
            return

        guild = message.guild
        if self._allowed_guilds:
            if guild is None or guild.id not in self._allowed_guilds:
                return

        text = (message.content or "").strip()
        if not text:
            return

        if self._discord_module is None:
            return

        # 判断消息是否提及机器人。
        user = self._client.user if self._client else None
        if user:
            bot_mention = user.mention  # 标准 ``<@ID>`` 提及形式。
            alt_mention = f"<@!{user.id}>"  # 带通知标记的 ``<@!ID>`` 提及形式。
            standard_mention = f"<@{user.id}>"
        else:
            bot_mention = None
            alt_mention = None
            standard_mention = ""
        has_mention = (bot_mention and bot_mention in message.content) or (alt_mention and alt_mention in message.content) or (standard_mention and standard_mention in message.content)

        # 删除提及标记，再将余下文本交给命令和会话处理。
        if has_mention:
            text = text.replace(bot_mention or "", "").replace(alt_mention or "", "").replace(standard_mention or "", "").strip()
            # 即使余下文本为空仍继续处理，以便仅提及时也能创建会话线程。

        connect_code = self._pending_connect_code(text)
        if connect_code and await self._bind_connection_from_connect_code(message, connect_code):
            return

        # 决定线程/频道路由，并选择应显示输入状态的目标。
        thread_id = None
        chat_id = None
        typing_target = None  # 用于显示输入状态的 Discord 线程或频道对象。

        if isinstance(message.channel, self._discord_module.Thread):
            # 消息已位于 Discord 线程内。
            thread_obj = message.channel
            thread_id = str(thread_obj.id)
            chat_id = str(thread_obj.parent_id or thread_obj.id)
            typing_target = thread_obj

            # 已记录的活动线程直接作为 DeerFlow 话题键处理。
            if thread_id in self._active_thread_ids:
                msg_type = InboundMessageType.COMMAND if is_known_channel_command(text) else InboundMessageType.CHAT
                inbound = self._make_inbound(
                    chat_id=chat_id,
                    user_id=str(message.author.id),
                    text=text,
                    msg_type=msg_type,
                    thread_ts=thread_id,
                    metadata={
                        "guild_id": str(guild.id) if guild else None,
                        "channel_id": str(message.channel.id),
                        "message_id": str(message.id),
                    },
                )
                inbound.topic_id = thread_id
                inbound = await self._attach_connection_identity(inbound, guild_id=str(guild.id) if guild else None)
                self._publish(inbound)
                # 在该线程内启动输入状态。
                if typing_target:
                    asyncio.create_task(self._start_typing(typing_target, chat_id, thread_id))
                asyncio.create_task(self._add_reaction(message))
                return

            # 未记录的孤立线程不复用，回退到下方的新会话路由。
            logger.debug("[Discord] message in orphaned thread %s, will create new thread", thread_id)
            thread_id = None
            typing_target = None

        # 处理至此的消息一定来自频道而非线程，因此统一应用仅提及规则。
        channel_id = str(message.channel.id)

        # 检查该频道是否已有活动 Discord 线程。
        if channel_id in self._active_threads:
            # 对频道根消息应用仅提及规则；允许频道除外。线程内续聊已在上方放行。
            if self._mention_only and not has_mention and channel_id not in self._allowed_channels:
                logger.debug("[Discord] skipping no-@ message in channel %s (not in thread)", channel_id)
                return
            # 仅提及模式下的新提及会创建新线程，而不是复用旧会话。
            if self._mention_only and has_mention:
                thread_obj = await self._create_thread(message)
                if thread_obj is not None:
                    target_thread_id = str(thread_obj.id)
                    self._record_thread_mapping(channel_id, target_thread_id)
                    await asyncio.to_thread(self._persist_thread_mappings)
                    thread_id = target_thread_id
                    chat_id = channel_id
                    typing_target = thread_obj
                    logger.info("[Discord] created new thread %s in channel %s on mention (replacing existing thread)", target_thread_id, channel_id)
                else:
                    logger.info("[Discord] thread creation failed in channel %s, falling back to channel replies", channel_id)
                    thread_id = channel_id
                    chat_id = channel_id
                    typing_target = message.channel
            else:
                # 将频道中的续聊路由到现有 Discord 线程。
                target_thread_id = self._active_threads[channel_id]
                logger.debug("[Discord] routing message in channel %s to existing thread %s", channel_id, target_thread_id)
                thread_id = target_thread_id
                chat_id = channel_id
                typing_target = await self._get_channel_or_thread(target_thread_id)
        elif self._mention_only and not has_mention and channel_id not in self._allowed_channels:
            # 未提及且不在允许频道内的消息不处理。
            logger.debug("[Discord] skipping message without mention in channel %s", channel_id)
            return
        elif self._mention_only and has_mention:
            # 此频道首次提及时创建 Discord 线程。
            thread_obj = await self._create_thread(message)
            if thread_obj is not None:
                target_thread_id = str(thread_obj.id)
                self._record_thread_mapping(channel_id, target_thread_id)
                await asyncio.to_thread(self._persist_thread_mappings)
                thread_id = target_thread_id
                chat_id = channel_id
                typing_target = thread_obj  # 在新线程中显示输入状态。
                logger.info("[Discord] created thread %s in channel %s for user %s", target_thread_id, channel_id, message.author.display_name)
            else:
                # 无法创建线程（未启用或无权限）时回退到频道回复。
                logger.info("[Discord] thread creation failed in channel %s, falling back to channel replies", channel_id)
                thread_id = channel_id
                chat_id = channel_id
                typing_target = message.channel  # 在频道中显示输入状态。
        elif self._thread_mode:
            # 未启用仅提及时，仍可按 thread_mode 创建线程以隔离会话。
            thread_obj = await self._create_thread(message)
            if thread_obj is None:
                # 无法创建线程（未启用或无权限）时回退到频道回复。
                logger.info("[Discord] thread creation failed in channel %s, falling back to channel replies", channel_id)
                thread_id = channel_id
                chat_id = channel_id
                typing_target = message.channel  # 在频道中显示输入状态。
            else:
                target_thread_id = str(thread_obj.id)
                self._record_thread_mapping(channel_id, target_thread_id)
                await asyncio.to_thread(self._persist_thread_mappings)
                thread_id = target_thread_id
                chat_id = channel_id
                typing_target = thread_obj  # 在新线程中显示输入状态。
        else:
            # 未启用线程模式时直接在频道中回复。
            thread_id = channel_id
            chat_id = channel_id
            typing_target = message.channel  # 在频道中显示输入状态。

        msg_type = InboundMessageType.COMMAND if is_known_channel_command(text) else InboundMessageType.CHAT
        inbound = self._make_inbound(
            chat_id=chat_id,
            user_id=str(message.author.id),
            text=text,
            msg_type=msg_type,
            thread_ts=thread_id,
            metadata={
                "guild_id": str(guild.id) if guild else None,
                "channel_id": str(message.channel.id),
                "message_id": str(message.id),
            },
        )
        inbound.topic_id = thread_id
        inbound = await self._attach_connection_identity(inbound, guild_id=str(guild.id) if guild else None)

        # 在最终选定的线程或频道中启动输入状态。
        if typing_target:
            asyncio.create_task(self._start_typing(typing_target, chat_id, thread_id))

        self._publish(inbound)
        asyncio.create_task(self._add_reaction(message))

    def _publish(self, inbound) -> None:
        """将入站消息线程安全地发布到主事件循环中的消息总线。"""
        if self._main_loop and self._main_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self.bus.publish_inbound(inbound), self._main_loop)
            future.add_done_callback(lambda f: logger.exception("[Discord] publish_inbound failed", exc_info=f.exception()) if f.exception() else None)

    async def _attach_connection_identity(self, inbound: InboundMessage, guild_id: str | None = None) -> InboundMessage:
        """按服务器优先、无服务器回退的范围，为入站消息附加已绑定的 DeerFlow 身份。"""
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="discord",
            workspace_id=guild_id,
            fallback_without_workspace=True,
        )

    async def _bind_connection_from_connect_code(self, message, code: str) -> bool:
        """消费连接码并将 Discord 外部账号、服务器和频道绑定到 DeerFlow 用户。"""
        if self._connection_repo is None or not code:
            return False

        state = await self._connection_repo.consume_oauth_state(provider="discord", state=code)
        if state is None:
            await self._send_connection_reply(message, "Discord connection code is invalid or expired.")
            return True

        guild = getattr(message, "guild", None)
        channel = getattr(message, "channel", None)
        author = getattr(message, "author", None)
        user_id = str(getattr(author, "id", "") or "")
        if not user_id:
            await self._send_connection_reply(message, "Discord connection could not be completed from this message.")
            return True

        guild_id = str(getattr(guild, "id", "") or "") or None
        await self._connection_repo.upsert_connection(
            owner_user_id=state["owner_user_id"],
            provider="discord",
            external_account_id=user_id,
            external_account_name=getattr(author, "display_name", None) or getattr(author, "name", None),
            workspace_id=guild_id,
            workspace_name=getattr(guild, "name", None) if guild is not None else None,
            metadata={
                "guild_id": guild_id,
                "channel_id": str(getattr(channel, "id", "") or ""),
            },
            status="connected",
        )
        await self._send_connection_reply(message, "Discord connected to DeerFlow.")
        return True

    @staticmethod
    async def _send_connection_reply(message, text: str) -> None:
        """向连接码所在频道发送绑定结果；无法发送时仅记录异常。"""
        channel = getattr(message, "channel", None)
        send = getattr(channel, "send", None)
        if send is None:
            return
        try:
            await send(text)
        except Exception:
            logger.exception("[Discord] failed to send connection reply")

    def _run_client(self) -> None:
        """在专用线程创建 Discord 事件循环并运行客户端，退出时尽力关闭客户端。"""
        self._discord_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._discord_loop)
        try:
            self._discord_loop.run_until_complete(self._client.start(self._bot_token))
        except Exception:
            if self._running:
                logger.exception("Discord client error")
        finally:
            try:
                if self._client and not self._client.is_closed():
                    self._discord_loop.run_until_complete(self._client.close())
            except Exception:
                logger.exception("Error during Discord shutdown")

    async def _create_thread(self, message):
        """为消息创建 Discord 线程；频道类型或权限不支持时返回 ``None``。"""
        try:
            if self._discord_module is None:
                return None

            # 仅文本频道和公告频道支持创建 Discord 线程。
            channel_type = message.channel.type
            if channel_type not in (
                self._discord_module.ChannelType.text,
                self._discord_module.ChannelType.news,
            ):
                logger.info(
                    "[Discord] channel type %s (%s) does not support threads",
                    channel_type.value,
                    channel_type.name,
                )
                return None

            thread_name = f"deerflow-{message.author.display_name}-{message.id}"[:100]
            return await message.create_thread(name=thread_name)
        except self._discord_module.errors.HTTPException as exc:
            if exc.code == 50024:
                logger.info(
                    "[Discord] cannot create thread in channel %s (error code 50024): %s",
                    message.channel.id,
                    channel_type.name if (channel_type := message.channel.type) else "unknown",
                )
            else:
                logger.exception(
                    "[Discord] failed to create thread for message=%s (HTTPException %s)",
                    message.id,
                    exc.code,
                )
            return None
        except Exception:
            logger.exception("[Discord] failed to create thread for message=%s (threads may be disabled or missing permissions)", message.id)
            return None

    async def _resolve_target(self, msg: OutboundMessage):
        """按 ``thread_ts`` 优先、``chat_id`` 兜底的顺序解析 Discord 回复目标。"""
        if not self._client or not self._discord_loop:
            return None

        target_ids: list[str] = []
        if msg.thread_ts:
            target_ids.append(msg.thread_ts)
        if msg.chat_id and msg.chat_id not in target_ids:
            target_ids.append(msg.chat_id)

        for raw_id in target_ids:
            target = await self._get_channel_or_thread(raw_id)
            if target is not None:
                return target
        return None

    async def _get_channel_or_thread(self, raw_id: str):
        """在 Discord 专用事件循环中按 ID 查询频道或线程。"""
        if not self._client or not self._discord_loop:
            return None

        try:
            target_id = int(raw_id)
        except (TypeError, ValueError):
            return None

        get_future = asyncio.run_coroutine_threadsafe(self._fetch_channel(target_id), self._discord_loop)
        try:
            return await asyncio.wrap_future(get_future)
        except Exception:
            logger.exception("[Discord] failed to resolve target id=%s", raw_id)
            return None

    async def _fetch_channel(self, target_id: int):
        """先读取 discord.py 缓存，未命中时请求远端频道或线程。"""
        if not self._client:
            return None

        channel = self._client.get_channel(target_id)
        if channel is not None:
            return channel

        try:
            return await self._client.fetch_channel(target_id)
        except Exception:
            return None

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """按 Discord 的 2000 字符限制切分文本，优先在换行处断开。"""
        if not text:
            return [""]

        chunks: list[str] = []
        remaining = text
        while len(remaining) > _DISCORD_MAX_MESSAGE_LEN:
            split_at = remaining.rfind("\n", 0, _DISCORD_MAX_MESSAGE_LEN)
            if split_at <= 0:
                split_at = _DISCORD_MAX_MESSAGE_LEN
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        if remaining:
            chunks.append(remaining)

        return chunks
