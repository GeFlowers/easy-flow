'''通过企业微信机器人 WebSocket 接收消息，并将智能体回复和附件回传给用户。'''

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from app.channels.base import Channel
from app.channels.commands import is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import (
    InboundMessage,
    InboundMessageType,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)

logger = logging.getLogger(__name__)


class WeComChannel(Channel):
    '''管理企业微信机器人连接、消息流、附件传输及账号绑定流程。'''

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        '''保存机器人配置，并初始化 WebSocket 连接、消息帧和流式响应状态。'''
        super().__init__(name="wecom", bus=bus, config=config)
        self._bot_id: str | None = None
        self._bot_secret: str | None = None
        self._ws_client = None
        self._ws_task: asyncio.Task | None = None
        self._ws_frames: dict[str, dict[str, Any]] = {}
        self._ws_stream_ids: dict[str, str] = {}
        self._working_message = "Working on it..."

    @property
    def supports_streaming(self) -> bool:
        '''声明该渠道支持通过企业微信流式消息逐步发送回复。'''
        return True

    def _clear_ws_context(self, thread_ts: str | None) -> None:
        '''清除指定消息线程缓存的请求帧和流式消息编号。'''
        if not thread_ts:
            return
        self._ws_frames.pop(thread_ts, None)
        self._ws_stream_ids.pop(thread_ts, None)

    async def _send_ws_upload_command(self, req_id: str, body: dict[str, Any], cmd: str) -> dict[str, Any]:
        '''通过 SDK 的 WebSocket 管理器发送媒体分片命令；接口不可用时报告配置错误。'''
        if not self._ws_client:
            raise RuntimeError("WeCom WebSocket client is not available")

        ws_manager = getattr(self._ws_client, "_ws_manager", None)
        send_reply = getattr(ws_manager, "send_reply", None)
        if not callable(send_reply):
            raise RuntimeError("Installed wecom-aibot-python-sdk does not expose the WebSocket media upload API expected by DeerFlow. Use wecom-aibot-python-sdk==0.1.6 or update the adapter.")

        send_reply_async = cast(Callable[[str, dict[str, Any], str], Awaitable[dict[str, Any]]], send_reply)
        return await send_reply_async(req_id, body, cmd)

    async def start(self) -> None:
        '''校验机器人凭据，注册各类消息及连接事件回调并启动后台连接任务。'''
        if self._running:
            return

        bot_id = self.config.get("bot_id")
        bot_secret = self.config.get("bot_secret")
        working_message = self.config.get("working_message")

        self._bot_id = bot_id if isinstance(bot_id, str) and bot_id else None
        self._bot_secret = bot_secret if isinstance(bot_secret, str) and bot_secret else None
        self._working_message = working_message if isinstance(working_message, str) and working_message else "Working on it..."

        if not self._bot_id or not self._bot_secret:
            logger.error("WeCom channel requires bot_id and bot_secret")
            return

        try:
            from aibot import WSClient, WSClientOptions
        except ImportError:
            logger.error("wecom-aibot-python-sdk is not installed. Install it with: uv add wecom-aibot-python-sdk")
            return
        else:
            self._ws_client = WSClient(WSClientOptions(bot_id=self._bot_id, secret=self._bot_secret, logger=logger))
            self._ws_client.on("message.text", self._on_ws_text)
            self._ws_client.on("message.mixed", self._on_ws_mixed)
            self._ws_client.on("message.image", self._on_ws_image)
            self._ws_client.on("message.file", self._on_ws_file)
            self._ws_client.on("error", self._on_ws_error)
            self._ws_client.on("disconnected", self._on_ws_disconnected)
            self._ws_task = asyncio.create_task(self._ws_client.connect())
            self._ws_task.add_done_callback(self._on_ws_task_done)

            self._running = True
            self.bus.subscribe_outbound(self._on_outbound)
        logger.info("WeCom channel started")

    def _on_ws_task_done(self, task: asyncio.Task) -> None:
        '''检查连接任务的结束状态，并记录未处理的连接异常。'''
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error(
            "WeCom WebSocket connection task failed: %s. Check that the network/proxy allows wss://openws.work.weixin.qq.com and that bot_id/bot_secret are valid.",
            exc,
        )

    def _on_ws_error(self, error: Any) -> None:
        '''记录 SDK 上报的 WebSocket 运行错误。'''
        logger.error("WeCom WebSocket error: %s", error)

    def _on_ws_disconnected(self, *args: Any) -> None:
        '''记录断连详情；重连工作由企业微信 SDK 负责。'''
        detail = f" ({args[0]})" if args else ""
        logger.warning("WeCom WebSocket disconnected%s; SDK will attempt to reconnect", detail)

    async def stop(self) -> None:
        '''取消机器人连接任务、解除事件订阅并清空连接及消息帧缓存。'''
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._ws_task:
            try:
                self._ws_task.cancel()
            except Exception:
                pass
            self._ws_task = None
        if self._ws_client:
            try:
                self._ws_client.disconnect()
            except Exception:
                pass
        self._ws_client = None
        self._ws_frames.clear()
        self._ws_stream_ids.clear()
        logger.info("WeCom channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        '''将回复发往机器人消息流；连接不可用时仅记录警告。'''
        if self._ws_client:
            await self._send_ws(msg, _max_retries=_max_retries)
            return
        logger.warning("[WeCom] send called but WebSocket client is not available")

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        '''过滤其他渠道的消息，发送本渠道回复及附件，并在最终回复后释放线程缓存。'''
        if msg.channel_name != self.name:
            return

        try:
            await self.send(msg)
        except Exception:
            logger.exception("Failed to send outbound message on channel %s", self.name)
            if msg.is_final:
                self._clear_ws_context(msg.thread_ts)
            return

        for attachment in msg.attachments:
            try:
                success = await self.send_file(msg, attachment)
                if not success:
                    logger.warning("[%s] file upload skipped for %s", self.name, attachment.filename)
            except Exception:
                logger.exception("[%s] failed to upload file %s", self.name, attachment.filename)

        if msg.is_final:
            self._clear_ws_context(msg.thread_ts)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        '''仅在最终回复时上传附件；按类型检查大小并将媒体发送到原消息会话。'''
        if not msg.is_final:
            return True
        if not self._ws_client:
            return False
        if not msg.thread_ts:
            return False
        frame = self._ws_frames.get(msg.thread_ts)
        if not frame:
            return False

        media_type = "image" if attachment.is_image else "file"
        size_limit = 2 * 1024 * 1024 if attachment.is_image else 20 * 1024 * 1024
        if attachment.size > size_limit:
            logger.warning(
                "[WeCom] %s too large (%d bytes), skipping: %s",
                media_type,
                attachment.size,
                attachment.filename,
            )
            return False

        try:
            media_id = await self._upload_media_ws(
                media_type=media_type,
                filename=attachment.filename,
                path=str(attachment.actual_path),
                size=attachment.size,
            )
            if not media_id:
                return False

            body = {media_type: {"media_id": media_id}, "msgtype": media_type}
            await self._ws_client.reply(frame, body)
            logger.debug("[WeCom] %s sent via ws: %s", media_type, attachment.filename)
            return True
        except Exception:
            logger.exception("[WeCom] failed to upload/send file via ws: %s", attachment.filename)
            return False

    async def _on_ws_text(self, frame: dict[str, Any]) -> None:
        '''提取文本消息及引用内容，忽略空消息后发布到内部消息总线。'''
        body = frame.get("body", {}) or {}
        text = ((body.get("text") or {}).get("content") or "").strip()
        quote = (((body.get("quote") or {}).get("text") or {}).get("content") or "").strip()
        if not text and not quote:
            return
        await self._publish_ws_inbound(frame, text + (f"\nQuote message: {quote}" if quote else ""))

    async def _on_ws_mixed(self, frame: dict[str, Any]) -> None:
        '''拆分混合消息中的文本、图片和文件条目，再统一发布为一条入站消息。'''
        body = frame.get("body", {}) or {}
        mixed = body.get("mixed") or {}
        items = mixed.get("msg_item") or []
        parts: list[str] = []
        files: list[dict[str, Any]] = []
        for item in items:
            item_type = (item or {}).get("msgtype")
            if item_type == "text":
                content = (((item or {}).get("text") or {}).get("content") or "").strip()
                if content:
                    parts.append(content)
            elif item_type in ("image", "file"):
                payload = (item or {}).get(item_type) or {}
                url = payload.get("url")
                aeskey = payload.get("aeskey")
                if isinstance(url, str) and url:
                    files.append(
                        {
                            "type": item_type,
                            "url": url,
                            "aeskey": (aeskey if isinstance(aeskey, str) and aeskey else None),
                        }
                    )
        text = "\n\n".join(parts).strip()
        if not text and not files:
            return
        if not text:
            text = "（receive image/file）"
        await self._publish_ws_inbound(frame, text, files=files)

    async def _on_ws_image(self, frame: dict[str, Any]) -> None:
        '''校验图片消息中的下载地址，并将图片附件元数据发布到入站消息。'''
        body = frame.get("body", {}) or {}
        image = body.get("image") or {}
        url = image.get("url")
        aeskey = image.get("aeskey")
        if not isinstance(url, str) or not url:
            return
        await self._publish_ws_inbound(
            frame,
            "（receive image ）",
            files=[
                {
                    "type": "image",
                    "url": url,
                    "aeskey": aeskey if isinstance(aeskey, str) and aeskey else None,
                }
            ],
        )

    async def _on_ws_file(self, frame: dict[str, Any]) -> None:
        '''校验文件消息中的下载地址，并将文件附件元数据发布到入站消息。'''
        body = frame.get("body", {}) or {}
        file_obj = body.get("file") or {}
        url = file_obj.get("url")
        aeskey = file_obj.get("aeskey")
        if not isinstance(url, str) or not url:
            return
        await self._publish_ws_inbound(
            frame,
            "（receive file）",
            files=[
                {
                    "type": "file",
                    "url": url,
                    "aeskey": aeskey if isinstance(aeskey, str) and aeskey else None,
                }
            ],
        )

    async def _publish_ws_inbound(
        self,
        frame: dict[str, Any],
        text: str,
        *,
        files: list[dict[str, Any]] | None = None,
    ) -> None:
        '''处理机器人入站帧、识别绑定码和命令，建立消息流并发布标准化消息。'''
        if not self._ws_client:
            return
        try:
            from aibot import generate_req_id
        except Exception:
            return

        body = frame.get("body", {}) or {}
        msg_id = body.get("msgid")
        if not msg_id:
            return

        user_id = (body.get("from") or {}).get("userid")

        connect_code = self._pending_connect_code(text)
        if connect_code:
            handled = await self._bind_connection_from_connect_code(
                frame=frame,
                user_id=str(user_id or ""),
                code=connect_code,
            )
            if handled:
                return

        inbound_type = InboundMessageType.COMMAND if is_known_channel_command(text) else InboundMessageType.CHAT
        inbound = self._make_inbound(
            chat_id=user_id,  # 将用户会话保留在内存中
            user_id=user_id,
            text=text,
            msg_type=inbound_type,
            thread_ts=msg_id,
            files=files or [],
            metadata={
                "aibotid": body.get("aibotid"),
                "chattype": body.get("chattype"),
                "message_id": msg_id,
            },
        )
        inbound.topic_id = user_id  # 沿用同一个线程

        stream_id = generate_req_id("stream")
        self._ws_frames[msg_id] = frame
        self._ws_stream_ids[msg_id] = stream_id

        try:
            await self._ws_client.reply_stream(frame, stream_id, self._working_message, False)
        except Exception:
            pass

        inbound = await self._attach_connection_identity(inbound)
        await self.bus.publish_inbound(inbound)

    async def _attach_connection_identity(self, inbound: InboundMessage) -> InboundMessage:
        '''根据工作区和外部用户信息，为入站消息补充已绑定的连接身份。'''
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="wecom",
            workspace_id=str(inbound.metadata.get("aibotid") or "") or None,
            fallback_without_workspace=True,
        )

    async def _bind_connection_from_connect_code(self, *, frame: dict[str, Any], user_id: str, code: str) -> bool:
        '''消费一次性连接码并绑定企业微信账号；无效码或缺少用户身份时向会话反馈。'''
        if self._connection_repo is None or not code:
            return False

        state = await self._connection_repo.consume_oauth_state(provider="wecom", state=code)
        if state is None:
            await self._send_connection_reply(frame, "WeCom connection code is invalid or expired.")
            return True

        if not user_id:
            await self._send_connection_reply(frame, "WeCom connection could not be completed from this message.")
            return True

        body = frame.get("body", {}) or {}
        workspace_id = str(body.get("aibotid") or "") or None
        await self._connection_repo.upsert_connection(
            owner_user_id=state["owner_user_id"],
            provider="wecom",
            external_account_id=user_id,
            workspace_id=workspace_id,
            metadata={
                "aibotid": workspace_id,
                "chattype": body.get("chattype"),
            },
            status="connected",
        )
        await self._send_connection_reply(frame, "WeCom connected to DeerFlow.")
        return True

    async def _send_connection_reply(self, frame: dict[str, Any], text: str) -> None:
        '''通过机器人当前消息帧向用户发送账号绑定结果文本。'''
        if not self._ws_client:
            return
        await self._ws_client.reply(frame, {"msgtype": "text", "text": {"content": text}})

    async def _send_ws(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        '''优先向原消息流发送增量回复；没有可用流时改为发送独立 Markdown 消息。'''
        if not self._ws_client:
            return
        try:
            from aibot import generate_req_id
        except Exception:
            generate_req_id = None

        if msg.thread_ts and msg.thread_ts in self._ws_frames:
            frame = self._ws_frames[msg.thread_ts]
            stream_id = self._ws_stream_ids.get(msg.thread_ts)
            if not stream_id and generate_req_id:
                stream_id = generate_req_id("stream")
                self._ws_stream_ids[msg.thread_ts] = stream_id
            if not stream_id:
                return

            await self._send_with_retry(
                lambda: self._ws_client.reply_stream(frame, stream_id, msg.text, bool(msg.is_final)),
                max_retries=_max_retries,
                log_prefix="[WeCom]",
                operation_name="stream send",
            )
            return

        body = {"msgtype": "markdown", "markdown": {"content": msg.text}}
        await self._send_with_retry(
            lambda: self._ws_client.send_message(msg.chat_id, body),
            max_retries=_max_retries,
            log_prefix="[WeCom]",
        )

    async def _upload_media_ws(
        self,
        *,
        media_type: str,
        filename: str,
        path: str,
        size: int,
    ) -> str | None:
        '''计算文件摘要并按企业微信协议分块上传媒体，完成后返回媒体编号。'''
        if not self._ws_client:
            return None
        try:
            from aibot import generate_req_id
        except Exception:
            return None

        chunk_size = 512 * 1024
        total_chunks = (size + chunk_size - 1) // chunk_size
        if total_chunks < 1 or total_chunks > 100:
            logger.warning("[WeCom] invalid total_chunks=%d for %s", total_chunks, filename)
            return None

        md5_hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                md5_hasher.update(chunk)
        md5 = md5_hasher.hexdigest()

        init_req_id = generate_req_id("aibot_upload_media_init")
        init_body = {
            "type": media_type,
            "filename": filename,
            "total_size": int(size),
            "total_chunks": int(total_chunks),
            "md5": md5,
        }
        init_ack = await self._send_ws_upload_command(init_req_id, init_body, "aibot_upload_media_init")
        upload_id = (init_ack.get("body") or {}).get("upload_id")
        if not upload_id:
            logger.warning("[WeCom] upload init returned no upload_id: %s", init_ack)
            return None

        with open(path, "rb") as f:
            for idx in range(total_chunks):
                data = f.read(chunk_size)
                if not data:
                    break
                chunk_req_id = generate_req_id("aibot_upload_media_chunk")
                chunk_body = {
                    "upload_id": upload_id,
                    "chunk_index": int(idx),
                    "base64_data": base64.b64encode(data).decode("utf-8"),
                }
                await self._send_ws_upload_command(chunk_req_id, chunk_body, "aibot_upload_media_chunk")

        finish_req_id = generate_req_id("aibot_upload_media_finish")
        finish_ack = await self._send_ws_upload_command(finish_req_id, {"upload_id": upload_id}, "aibot_upload_media_finish")
        media_id = (finish_ack.get("body") or {}).get("media_id")
        if not media_id:
            logger.warning("[WeCom] upload finish returned no media_id: %s", finish_ack)
            return None
        return media_id
