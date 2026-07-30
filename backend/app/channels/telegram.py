"""通过长轮询接入 Telegram 通道，无需公开 HTTP 回调地址。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from app.channels.base import Channel
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
STREAM_EDIT_MIN_INTERVAL_SECONDS = 1.0
# Telegram 对负数 chat_id 的群组限制为每分钟 20 条消息，因此流式编辑间隔
# 必须显著低于私聊每秒一条消息的建议频率。
STREAM_EDIT_GROUP_MIN_INTERVAL_SECONDS = 3.0
# 在途流式消息的追踪上限；正常会在最终更新时清除，仅用于防止最终更新缺失时泄漏。
MAX_TRACKED_STREAM_MESSAGES = 256

# 通过间接引用时钟，测试可替换该时钟而不修改全局 time 模块。
_monotonic = time.monotonic


class TelegramChannel(Channel):
    """使用长轮询的 Telegram 机器人通道。

    ``bot_token`` 为 Telegram Bot API 令牌；``allowed_users`` 为可选的用户 ID
    白名单，空列表表示允许所有用户。
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        """初始化 Telegram 应用、用户白名单、回复链和流式编辑状态。"""
        super().__init__(name="telegram", bus=bus, config=config)
        self._application = None
        self._thread: threading.Thread | None = None
        self._tg_loop: asyncio.AbstractEventLoop | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._allowed_users: set[int] = set()
        for uid in config.get("allowed_users", []):
            try:
                self._allowed_users.add(int(uid))
            except (ValueError, TypeError):
                pass
        # 保存每个聊天最后发送的机器人消息 ID，用于串联回复。
        self._last_bot_message: dict[str, int] = {}
        # 以 ``chat_id:thread_ts`` 为键，记录原地编辑的在途流式机器人消息状态。
        self._stream_messages: dict[str, dict[str, Any]] = {}

    @property
    def supports_streaming(self) -> bool:
        """声明该通道支持通过编辑同一条 Telegram 消息呈现流式输出。"""
        return True

    async def start(self) -> None:
        """构建处理器并在独立线程的事件循环中启动 Telegram 长轮询。"""
        if self._running:
            return

        try:
            from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
        except ImportError:
            logger.error("python-telegram-bot is not installed. Install it with: uv add python-telegram-bot")
            return

        bot_token = self.config.get("bot_token", "")
        if not bot_token:
            logger.error("Telegram channel requires bot_token")
            return

        self._main_loop = asyncio.get_event_loop()
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # 构建 Telegram 应用实例。
        app = ApplicationBuilder().token(bot_token).build()

        # 注册固定的斜杠命令处理器。
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("bootstrap", self._cmd_generic))
        app.add_handler(CommandHandler("new", self._cmd_generic))
        app.add_handler(CommandHandler("status", self._cmd_generic))
        app.add_handler(CommandHandler("models", self._cmd_generic))
        app.add_handler(CommandHandler("memory", self._cmd_generic))
        app.add_handler(CommandHandler("goal", self._cmd_generic))
        app.add_handler(CommandHandler("help", self._cmd_generic))

        # 技能命令动态生成，无法全部预注册，因此将未知斜杠命令交给文本处理器。
        app.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, self._on_text))

        # 注册普通文本消息处理器。
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

        self._application = app

        # 在拥有独立事件循环的专用线程中执行轮询。
        self._thread = threading.Thread(target=self._run_polling, daemon=True)
        self._thread.start()
        logger.info("Telegram channel started")

    async def stop(self) -> None:
        """停止轮询事件循环、解除总线订阅并回收轮询线程。"""
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._tg_loop and self._tg_loop.is_running():
            self._tg_loop.call_soon_threadsafe(self._tg_loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        self._application = None
        logger.info("Telegram channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        """发送 Telegram 输出：增量原地编辑，最终消息完成编辑或按重试策略新发。"""
        if not self._application:
            return

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("Invalid Telegram chat_id: %s", msg.chat_id)
            return

        key = self._stream_key(msg.chat_id, msg.thread_ts)

        if not msg.is_final:
            await self._send_stream_update(chat_id, key, msg.text, reply_to=self._parse_message_id(msg.thread_ts))
            return

        state = self._stream_messages.pop(key, None)
        if state is not None:
            await self._finalize_stream_message(chat_id, msg.chat_id, state, msg.text)
            return

        await self._send_new_message(chat_id, msg.chat_id, msg.text, _max_retries=_max_retries)

    async def _send_stream_update(self, chat_id: int, key: str, text: str, reply_to: int | None = None) -> None:
        """以累计文本编辑在途流式消息。

        增量更新为尽力而为：节流或限流时直接丢弃；消息管理器随后一定会发布最终消息，
        因而完整文本仍可送达。
        """
        if not text:
            return

        display = text
        if len(display) > TELEGRAM_MAX_MESSAGE_LENGTH:
            display = display[: TELEGRAM_MAX_MESSAGE_LENGTH - 1] + "…"

        bot = self._application.bot
        state = self._stream_messages.get(key)

        send_kwargs: dict[str, Any] = {"chat_id": chat_id, "text": display}
        if reply_to:
            send_kwargs["reply_to_message_id"] = reply_to

        if state is None:
            try:
                sent = await bot.send_message(**send_kwargs)
            except Exception:
                logger.exception("[Telegram] failed to start stream message in chat=%s", chat_id)
                return
            self._register_stream_message(key, message_id=sent.message_id, last_text=display, last_edit_at=_monotonic())
            return

        now = _monotonic()
        min_interval = STREAM_EDIT_GROUP_MIN_INTERVAL_SECONDS if chat_id < 0 else STREAM_EDIT_MIN_INTERVAL_SECONDS
        if now - state["last_edit_at"] < min_interval:
            return
        if display == state["last_text"]:
            return

        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=state["message_id"], text=display)
        except Exception as exc:
            if self._is_not_modified(exc):
                state["last_text"] = display
                return
            if self._is_retry_after(exc):
                logger.debug("[Telegram] stream edit rate-limited in chat=%s, dropping update", chat_id)
                return
            logger.warning("[Telegram] stream edit failed in chat=%s, sending new message: %s", chat_id, exc)
            try:
                sent = await bot.send_message(**send_kwargs)
            except Exception:
                logger.exception("[Telegram] failed to send fallback stream message in chat=%s", chat_id)
                return
            state["message_id"] = sent.message_id

        state["last_edit_at"] = _monotonic()
        state["last_text"] = display

    async def _finalize_stream_message(self, chat_id: int, chat_key: str, state: dict[str, Any], text: str) -> None:
        """写入最终文本：编辑流式消息，超长部分拆分为后续消息。"""
        bot = self._application.bot
        chunks = self._split_message(text or "")

        edited = True
        if chunks[0] != state["last_text"]:
            edited = await self._edit_final_chunk(bot, chat_id, state["message_id"], chunks[0])

        if edited:
            self._last_bot_message[chat_key] = state["message_id"]
        else:
            # 编辑无法应用（如消息已删除）时，按标准重试策略新发首个分段。
            await self._send_new_message(chat_id, chat_key, chunks[0])

        for chunk in chunks[1:]:
            await self._send_new_message(chat_id, chat_key, chunk)

    async def _edit_final_chunk(self, bot, chat_id: int, message_id: int, text: str) -> bool:
        """编辑最终分段，遇到限流只重试一次；无法编辑时返回 ``False``。"""
        for attempt in range(2):
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
                return True
            except Exception as exc:
                if self._is_not_modified(exc):
                    return True
                if self._is_retry_after(exc) and attempt == 0:
                    await asyncio.sleep(self._retry_after_seconds(exc))
                    continue
                logger.warning("[Telegram] final edit failed in chat=%s: %s", chat_id, exc)
                return False
        return False

    async def _send_new_message(self, chat_id: int, chat_key: str, text: str, *, _max_retries: int = 3) -> int | None:
        """按退避重试策略发送新消息，并返回成功发送后的消息 ID。"""
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}

        # 回复此聊天中最后一条机器人消息，以维持 Telegram 回复链。
        reply_to = self._last_bot_message.get(chat_key)
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to

        bot = self._application.bot

        async def send_message() -> int:
            """调用 Telegram API 并将新消息记录为该聊天的最新机器人消息。"""
            sent = await bot.send_message(**kwargs)
            self._last_bot_message[chat_key] = sent.message_id
            return sent.message_id

        return await self._send_with_retry(
            send_message,
            max_retries=_max_retries,
            log_prefix="[Telegram]",
        )

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """按大小和类型将附件作为图片或文档发送，并接入当前聊天的回复链。"""
        if not self._application:
            return False

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("[Telegram] Invalid chat_id: %s", msg.chat_id)
            return False

        # Telegram 对图片限制 10MB，对文档限制 50MB。
        if attachment.size > 50 * 1024 * 1024:
            logger.warning("[Telegram] file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        bot = self._application.bot
        reply_to = self._last_bot_message.get(msg.chat_id)

        try:
            if attachment.is_image and attachment.size <= 10 * 1024 * 1024:
                with open(attachment.actual_path, "rb") as f:
                    kwargs: dict[str, Any] = {"chat_id": chat_id, "photo": f}
                    if reply_to:
                        kwargs["reply_to_message_id"] = reply_to
                    sent = await bot.send_photo(**kwargs)
            else:
                from telegram import InputFile

                with open(attachment.actual_path, "rb") as f:
                    input_file = InputFile(f, filename=attachment.filename)
                    kwargs = {"chat_id": chat_id, "document": input_file}
                    if reply_to:
                        kwargs["reply_to_message_id"] = reply_to
                    sent = await bot.send_document(**kwargs)

            self._last_bot_message[msg.chat_id] = sent.message_id
            logger.info("[Telegram] file sent: %s to chat=%s", attachment.filename, msg.chat_id)
            return True
        except Exception:
            logger.exception("[Telegram] failed to send file: %s", attachment.filename)
            return False

    # 以下为流式状态、重试判断、轮询和身份绑定的内部辅助方法。

    @staticmethod
    def _stream_key(chat_id: str, thread_ts: str | None) -> str:
        """构造隔离流式编辑状态的 ``chat_id:thread_ts`` 键。"""
        return f"{chat_id}:{thread_ts or ''}"

    @staticmethod
    def _parse_message_id(value: str | None) -> int | None:
        """将可选字符串安全转换为 Telegram 整数消息 ID。"""
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def _register_stream_message(self, key: str, *, message_id: int, last_text: str, last_edit_at: float) -> None:
        """登记在途流式消息，并在达到上限时淘汰最早追踪项。"""
        self._stream_messages.pop(key, None)
        while len(self._stream_messages) >= MAX_TRACKED_STREAM_MESSAGES:
            self._stream_messages.pop(next(iter(self._stream_messages)))
        self._stream_messages[key] = {
            "message_id": message_id,
            "last_edit_at": last_edit_at,
            "last_text": last_text,
        }

    @staticmethod
    def _is_retry_after(exc: Exception) -> bool:
        """判断 Telegram 异常是否携带服务器要求的重试等待时间。"""
        return getattr(exc, "retry_after", None) is not None

    @staticmethod
    def _retry_after_seconds(exc: Exception) -> float:
        """将 Telegram 异常中的重试等待值统一转换为秒数。"""
        value = getattr(exc, "retry_after", 0)
        if hasattr(value, "total_seconds"):
            return float(value.total_seconds())
        return float(value)

    @staticmethod
    def _is_not_modified(exc: Exception) -> bool:
        """判断编辑失败是否仅因目标消息文本未发生变化。"""
        return "message is not modified" in str(exc).lower()

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """按 Telegram 4096 字符限制将文本切为至少一个分段。"""
        return [text[i : i + TELEGRAM_MAX_MESSAGE_LENGTH] for i in range(0, len(text), TELEGRAM_MAX_MESSAGE_LENGTH)] or [text]

    async def _send_running_reply(self, chat_id: str, reply_to_message_id: int) -> None:
        """发送处理中回复，并将其登记为后续流式编辑的目标消息。"""
        if not self._application:
            return
        try:
            bot = self._application.bot
            sent = await bot.send_message(
                chat_id=int(chat_id),
                text="Working on it...",
                reply_to_message_id=reply_to_message_id,
            )
            self._register_stream_message(
                self._stream_key(chat_id, str(reply_to_message_id)),
                message_id=sent.message_id,
                last_text="Working on it...",
                last_edit_at=0.0,
            )
            logger.info("[Telegram] 'Working on it...' reply sent in chat=%s", chat_id)
        except Exception:
            logger.exception("[Telegram] failed to send running reply in chat=%s", chat_id)

    def _run_polling(self) -> None:
        """在专用线程中运行 Telegram 轮询及其独立事件循环。"""
        self._tg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._tg_loop)
        try:
            # ``run_polling`` 会调用仅主线程可用的信号处理器，因此改为手动初始化
            # 应用并启动更新器。
            self._tg_loop.run_until_complete(self._application.initialize())
            self._tg_loop.run_until_complete(self._application.start())
            self._tg_loop.run_until_complete(self._application.updater.start_polling())
            self._tg_loop.run_forever()
        except Exception:
            if self._running:
                logger.exception("Telegram polling error")
        finally:
            # 尽力完成优雅关闭。
            try:
                if self._application.updater.running:
                    self._tg_loop.run_until_complete(self._application.updater.stop())
                self._tg_loop.run_until_complete(self._application.stop())
                self._tg_loop.run_until_complete(self._application.shutdown())
            except Exception:
                logger.exception("Error during Telegram shutdown")

    def _check_user(self, user_id: int) -> bool:
        """在白名单为空时允许所有用户，否则仅允许已配置的 Telegram 用户。"""
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    @staticmethod
    def _telegram_display_name(user) -> str:
        """按全名、用户名、用户 ID 的优先级取得用于身份绑定的展示名。"""
        full_name = getattr(user, "full_name", None)
        if isinstance(full_name, str) and full_name:
            return full_name
        username = getattr(user, "username", None)
        if isinstance(username, str) and username:
            return username
        return str(getattr(user, "id", ""))

    async def _bind_connection_from_start_token(self, update, state_token: str) -> bool:
        """消费深链启动令牌，将 Telegram 用户和聊天绑定到 DeerFlow 用户。"""
        if self._connection_repo is None or not state_token:
            return False

        state = await self._connection_repo.consume_oauth_state(provider="telegram", state=state_token)
        if state is None:
            await update.message.reply_text("Telegram connection link is invalid or expired.")
            return True

        owner_user_id = state["owner_user_id"]
        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)
        connection = await self._connection_repo.upsert_connection(
            owner_user_id=owner_user_id,
            provider="telegram",
            external_account_id=user_id,
            external_account_name=self._telegram_display_name(update.effective_user),
            workspace_id=chat_id,
            workspace_name=None,
            metadata={
                "chat_id": chat_id,
                "chat_type": update.effective_chat.type,
                "telegram_username": getattr(update.effective_user, "username", None),
            },
            status="connected",
        )
        logger.info("[Telegram] bound chat=%s user=%s to DeerFlow user=%s connection=%s", chat_id, user_id, owner_user_id, connection["id"])
        await update.message.reply_text("Telegram connected to DeerFlow.")
        return True

    async def _attach_connection_identity(self, inbound: InboundMessage) -> InboundMessage:
        """以 Telegram 聊天 ID 为工作区键，为入站消息附加已绑定的身份。"""
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="telegram",
            workspace_id=inbound.chat_id,
        )

    def _get_bot_username(self, context) -> str | None:
        """从回调上下文优先、应用实例兜底获取当前机器人的用户名。"""
        bot = getattr(context, "bot", None)
        username = getattr(bot, "username", None)
        if not username and self._application is not None:
            username = getattr(getattr(self._application, "bot", None), "username", None)
        return str(username) if username else None

    @staticmethod
    def _strip_bot_username_from_leading_command(text: str, bot_username: str | None) -> str:
        """移除指向当前机器人的命令用户名后缀，保留命令参数和其他机器人命令。"""
        username = (bot_username or "").lstrip("@").lower()
        if not username or not text.startswith("/"):
            return text

        parts = text.split(maxsplit=1)
        command_token = parts[0]
        if "@" not in command_token:
            return text

        command_name, addressed_username = command_token[1:].rsplit("@", 1)
        if not command_name or addressed_username.lower() != username:
            return text

        normalized = f"/{command_name}"
        if len(parts) > 1:
            normalized = f"{normalized} {parts[1]}"
        return normalized

    async def _cmd_start(self, update, context) -> None:
        """处理 ``/start``：优先消费深链绑定令牌，否则向允许用户发送欢迎语。"""
        args = getattr(context, "args", []) if context is not None else []
        if args:
            # 在白名单判断前处理深链绑定令牌，使浏览器可建立新的外部身份。
            handled = await self._bind_connection_from_start_token(update, str(args[0]))
            if handled:
                return
        if not self._check_user(update.effective_user.id):
            return
        await update.message.reply_text("Welcome to DeerFlow! Send me a message to start a conversation.\nType /help for available commands.")

    async def _process_incoming_with_reply(self, chat_id: str, msg_id: int, inbound: InboundMessage) -> None:
        """先创建可编辑的处理中回复，再向消息总线发布入站消息。"""
        await self._send_running_reply(chat_id, msg_id)
        await self.bus.publish_inbound(inbound)

    async def _cmd_generic(self, update, context) -> None:
        """标准化并转发斜杠命令，同时沿用文本消息的话题键规则。"""
        if not self._check_user(update.effective_user.id):
            return

        text = self._strip_bot_username_from_leading_command(update.message.text.strip(), self._get_bot_username(context))
        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        msg_id = str(update.message.message_id)

        # 与文本消息使用同一话题键规则，确保新建会话等命令作用于正确会话。
        if update.effective_chat.type == "private":
            topic_id = None
        else:
            reply_to = update.message.reply_to_message
            if reply_to:
                topic_id = str(reply_to.message_id)
            else:
                topic_id = msg_id

        inbound = self._make_inbound(
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=InboundMessageType.COMMAND,
            thread_ts=msg_id,
            metadata={"message_id": msg_id},
        )
        inbound.topic_id = topic_id
        inbound = await self._attach_connection_identity(inbound)

        if self._main_loop and self._main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._process_incoming_with_reply(chat_id, update.message.message_id, inbound), self._main_loop)
            fut.add_done_callback(lambda f: self._log_future_error(f, "process_incoming_with_reply", update.message.message_id))
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")

    async def _on_text(self, update, context) -> None:
        """处理普通文本，计算 Telegram 话题键并附加连接身份后发布。"""
        if not self._check_user(update.effective_user.id):
            return

        text = self._strip_bot_username_from_leading_command(update.message.text.strip(), self._get_bot_username(context))
        if not text:
            return

        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        msg_id = str(update.message.message_id)

        # 话题键决定消息映射到哪个 DeerFlow 线程：私聊不设置话题键，
        # 所有消息共享当前聊天的存储键；群聊使用被回复消息 ID 或当前
        # 消息 ID，从而保持各个回复链的会话隔离。
        if update.effective_chat.type == "private":
            topic_id = None
        else:
            reply_to = update.message.reply_to_message
            if reply_to:
                topic_id = str(reply_to.message_id)
            else:
                topic_id = msg_id

        inbound = self._make_inbound(
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=InboundMessageType.CHAT,
            thread_ts=msg_id,
            metadata={"message_id": msg_id},
        )
        inbound.topic_id = topic_id
        inbound = await self._attach_connection_identity(inbound)

        if self._main_loop and self._main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._process_incoming_with_reply(chat_id, update.message.message_id, inbound), self._main_loop)
            fut.add_done_callback(lambda f: self._log_future_error(f, "process_incoming_with_reply", update.message.message_id))
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")
