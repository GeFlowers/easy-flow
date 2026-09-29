"""通过飞书长连接收发消息、附件和运行状态卡片。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any, Literal

from app.channels.base import Channel
from app.channels.commands import is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import (
    PENDING_CLARIFICATION_METADATA_KEY,
    RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY,
    InboundMessage,
    InboundMessageType,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import get_sandbox_provider

logger = logging.getLogger(__name__)
PENDING_CLARIFICATION_TTL_SECONDS = 30 * 60
FEISHU_INBOUND_BATCH_WINDOW_SECONDS = 0.75
SOURCE_PREVIEW_METADATA_KEY = "feishu_source_preview"


def _is_feishu_command(text: str) -> bool:
    """判断文本是否为项目支持的飞书斜杠命令。"""
    return is_known_channel_command(text)


class FeishuChannel(Channel):
    """飞书消息通道：以 WebSocket 接收事件，并用卡片展示 Agent 运行进度和结果。"""

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        """初始化飞书 SDK 状态、后台任务、消息批次和待澄清记录。"""
        super().__init__(name="feishu", bus=bus, config=config)
        self._thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._api_client = None
        self._CreateMessageReactionRequest = None
        self._CreateMessageReactionRequestBody = None
        self._Emoji = None
        self._PatchMessageRequest = None
        self._PatchMessageRequestBody = None
        self._background_tasks: set[asyncio.Task] = set()
        self._running_card_ids: dict[str, str] = {}
        self._running_card_tasks: dict[str, asyncio.Task] = {}
        self._pending_clarifications: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._pending_inbound_batches: dict[tuple[str, str], dict[str, Any]] = {}
        self._CreateFileRequest = None
        self._CreateFileRequestBody = None
        self._CreateImageRequest = None
        self._CreateImageRequestBody = None
        self._GetMessageResourceRequest = None
        self._thread_lock = threading.Lock()

    @staticmethod
    def _non_empty_str(value: Any) -> str | None:
        """将非空字符串去除首尾空白后返回，其他值转换为 None。"""
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _pending_key(chat_id: str, user_id: str) -> tuple[str, str]:
        """生成待澄清消息缓存使用的聊天与用户组合键。"""
        return (chat_id, user_id)

    @staticmethod
    def _should_include_source_preview(
        *,
        chat_type: str | None,
        root_id: str | None,
        parent_id: str | None,
        thread_id: str | None,
    ) -> bool:
        """仅在群聊且消息属于话题或回复上下文时附带原消息摘要。"""
        if chat_type == "p2p":
            return False
        return bool(root_id or parent_id or thread_id)

    @staticmethod
    def _compact_source_preview(text: str) -> str | None:
        """压缩原消息摘要为最多三行、240 字符，空内容返回 None。"""
        stripped = text.strip()
        if not stripped:
            return None

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return None
        preview = "\n".join(lines[:3])
        if len(preview) > 240:
            preview = preview[:237].rstrip() + "..."
        return preview

    @classmethod
    def _compose_card_text(cls, text: str, metadata: dict[str, Any] | None = None) -> str:
        """将可选的原消息摘要引用与 Agent 回复合并为卡片正文。"""
        preview = None
        if isinstance(metadata, dict):
            raw_preview = metadata.get(SOURCE_PREVIEW_METADATA_KEY)
            if isinstance(raw_preview, str) and raw_preview.strip():
                preview = raw_preview.strip()
        if not preview:
            return text

        quoted_preview = "\n".join(f"> {line}" for line in preview.splitlines())
        return f"{quoted_preview}\n\n{text}"

    @property
    def supports_streaming(self) -> bool:
        """声明该通道支持通过运行卡片持续展示处理进度。"""
        return True

    @property
    def is_running(self) -> bool:
        """检查通道是否已启动且其 WebSocket 工作线程仍存活。"""
        if not self._running:
            return False
        return self._thread is not None and self._thread.is_alive()

    def _build_event_handler(self, lark):
        """注册飞书消息接收回调，并将无业务处理的事件交给忽略处理器。"""
        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .register_p2_im_message_message_read_v1(self._on_ignored_message_event)
            .register_p2_im_message_reaction_created_v1(self._on_ignored_message_event)
            .register_p2_im_message_reaction_deleted_v1(self._on_ignored_message_event)
            .register_p2_im_message_recalled_v1(self._on_ignored_message_event)
            .build()
        )

    async def start(self) -> None:
        """加载飞书 SDK、校验凭证并启动独立事件循环上的 WebSocket 客户端。"""
        if self._running:
            return

        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateFileRequest,
                CreateFileRequestBody,
                CreateImageRequest,
                CreateImageRequestBody,
                CreateMessageReactionRequest,
                CreateMessageReactionRequestBody,
                CreateMessageRequest,
                CreateMessageRequestBody,
                Emoji,
                GetMessageResourceRequest,
                PatchMessageRequest,
                PatchMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )
        except ImportError:
            logger.error("lark-oapi is not installed. Install it with: uv add lark-oapi")
            return

        self._lark = lark
        self._CreateMessageRequest = CreateMessageRequest
        self._CreateMessageRequestBody = CreateMessageRequestBody
        self._ReplyMessageRequest = ReplyMessageRequest
        self._ReplyMessageRequestBody = ReplyMessageRequestBody
        self._CreateMessageReactionRequest = CreateMessageReactionRequest
        self._CreateMessageReactionRequestBody = CreateMessageReactionRequestBody
        self._Emoji = Emoji
        self._PatchMessageRequest = PatchMessageRequest
        self._PatchMessageRequestBody = PatchMessageRequestBody
        self._CreateFileRequest = CreateFileRequest
        self._CreateFileRequestBody = CreateFileRequestBody
        self._CreateImageRequest = CreateImageRequest
        self._CreateImageRequestBody = CreateImageRequestBody
        self._GetMessageResourceRequest = GetMessageResourceRequest

        app_id = self.config.get("app_id", "")
        app_secret = self.config.get("app_secret", "")
        domain = self.config.get("domain", "https://open.feishu.cn")

        if not app_id or not app_secret:
            logger.error("Feishu channel requires app_id and app_secret")
            return

        self._api_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).domain(domain).build()
        logger.info("[Feishu] using domain: %s", domain)
        self._main_loop = asyncio.get_event_loop()

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # ws.Client 的构造和启动都必须位于独立线程及事件循环中。lark-oapi 会缓存构造时的循环，
        # 并在 start() 中调用 run_until_complete()；若复用已运行的 uvloop 会触发运行时错误。
        self._thread = threading.Thread(
            target=self._run_ws,
            args=(app_id, app_secret, domain),
            daemon=True,
        )
        self._thread.start()
        logger.info("Feishu channel started")

    def _run_ws(self, app_id: str, app_secret: str, domain: str) -> None:
        """在线程专属事件循环中运行飞书 SDK，避免复用 Uvicorn 正在运行的主循环。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import lark_oapi as lark
            import lark_oapi.ws.client as _ws_client_mod

            # 将 SDK 缓存的循环替换为当前线程的循环，避免在运行中的主循环上再次启动。
            _ws_client_mod.loop = loop

            event_handler = self._build_event_handler(lark)
            ws_client = lark.ws.Client(
                app_id=app_id,
                app_secret=app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO,
                domain=domain,
            )
            ws_client.start()
        except Exception:
            if self._running:
                logger.exception("Feishu WebSocket error")
            self._running = False

    def _on_ignored_message_event(self, event) -> None:
        """记录当前不参与会话处理的飞书事件类型。"""
        logger.debug("[Feishu] ignoring non-content message event: %s", type(event).__name__)

    async def stop(self) -> None:
        """停止接收消息、取消后台任务并等待 WebSocket 工作线程退出。"""
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        for task in list(self._background_tasks):
            task.cancel()
        self._background_tasks.clear()
        for task in list(self._running_card_tasks.values()):
            task.cancel()
        self._running_card_tasks.clear()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Feishu channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        """将出站回复构造成飞书卡片发送，并对临时失败进行重试。"""
        if not self._api_client:
            logger.warning("[Feishu] send called but no api_client available")
            return

        logger.info(
            "[Feishu] sending reply: chat_id=%s, thread_ts=%s, text_len=%d",
            msg.chat_id,
            msg.thread_ts,
            len(msg.text),
        )

        await self._send_with_retry(
            lambda: self._send_card_message(msg),
            max_retries=_max_retries,
            log_prefix="[Feishu]",
        )

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """上传图片或文件并发送到会话；超限或发送失败时返回 False。"""
        if not self._api_client:
            return False

        # 飞书图片和普通文件分别有 10 MB 与 30 MB 的上传限制。
        if attachment.is_image and attachment.size > 10 * 1024 * 1024:
            logger.warning("[Feishu] image too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False
        if not attachment.is_image and attachment.size > 30 * 1024 * 1024:
            logger.warning("[Feishu] file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        try:
            if attachment.is_image:
                file_key = await self._upload_image(attachment.actual_path)
                msg_type = "image"
                content = json.dumps({"image_key": file_key})
            else:
                file_key = await self._upload_file(attachment.actual_path, attachment.filename)
                msg_type = "file"
                content = json.dumps({"file_key": file_key})

            if msg.thread_ts:
                request = self._ReplyMessageRequest.builder().message_id(msg.thread_ts).request_body(self._ReplyMessageRequestBody.builder().msg_type(msg_type).content(content).build()).build()
                await asyncio.to_thread(self._api_client.im.v1.message.reply, request)
            else:
                request = self._CreateMessageRequest.builder().receive_id_type("chat_id").request_body(self._CreateMessageRequestBody.builder().receive_id(msg.chat_id).msg_type(msg_type).content(content).build()).build()
                await asyncio.to_thread(self._api_client.im.v1.message.create, request)

            logger.info("[Feishu] file sent: %s (type=%s)", attachment.filename, msg_type)
            return True
        except Exception:
            logger.exception("[Feishu] failed to upload/send file: %s", attachment.filename)
            return False

    async def _upload_image(self, path) -> str:
        """上传图片到飞书，成功后返回消息引用所需的 image_key。"""
        with open(str(path), "rb") as f:
            request = self._CreateImageRequest.builder().request_body(self._CreateImageRequestBody.builder().image_type("message").image(f).build()).build()
            response = await asyncio.to_thread(self._api_client.im.v1.image.create, request)
        if not response.success():
            raise RuntimeError(f"Feishu image upload failed: code={response.code}, msg={response.msg}")
        return response.data.image_key

    async def _upload_file(self, path, filename: str) -> str:
        """按扩展名选择飞书文件类型并上传，成功后返回 file_key。"""
        suffix = path.suffix.lower() if hasattr(path, "suffix") else ""
        if suffix in (".xls", ".xlsx", ".csv"):
            file_type = "xls"
        elif suffix in (".ppt", ".pptx"):
            file_type = "ppt"
        elif suffix == ".pdf":
            file_type = "pdf"
        elif suffix in (".doc", ".docx"):
            file_type = "doc"
        else:
            file_type = "stream"

        with open(str(path), "rb") as f:
            request = self._CreateFileRequest.builder().request_body(self._CreateFileRequestBody.builder().file_type(file_type).file_name(filename).file(f).build()).build()
            response = await asyncio.to_thread(self._api_client.im.v1.file.create, request)
        if not response.success():
            raise RuntimeError(f"Feishu file upload failed: code={response.code}, msg={response.msg}")
        return response.data.file_key

    async def receive_file(self, msg: InboundMessage, thread_id: str, *, user_id: str | None = None) -> InboundMessage:
        """下载入站消息中的图片和文件，将占位文本替换为沙箱上传路径。"""
        if not msg.thread_ts:
            logger.warning("[Feishu] received file message without thread_ts, cannot associate with conversation: %s", msg)
            return msg
        files = msg.files
        if not files:
            logger.warning("[Feishu] received message with no files: %s", msg)
            return msg
        text = msg.text
        for file in files:
            if file.get("image_key"):
                virtual_path = await self._receive_single_file(msg.thread_ts, file["image_key"], "image", thread_id, user_id=user_id)
                text = text.replace("[image]", virtual_path, 1)
            elif file.get("file_key"):
                virtual_path = await self._receive_single_file(msg.thread_ts, file["file_key"], "file", thread_id, user_id=user_id)
                text = text.replace("[file]", virtual_path, 1)
        msg.text = text
        return msg

    async def _receive_single_file(
        self,
        message_id: str,
        file_key: str,
        type: Literal["image", "file"],
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> str:
        """获取单个飞书资源并保存到线程上传目录，返回虚拟路径或错误提示。"""
        request = self._GetMessageResourceRequest.builder().message_id(message_id).file_key(file_key).type(type).build()

        def inner():
            """调用飞书消息资源接口下载指定文件流。"""
            return self._api_client.im.v1.message_resource.get(request)

        try:
            response = await asyncio.to_thread(inner)
        except Exception:
            logger.exception("[Feishu] resource get request failed for resource_key=%s type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"

        if not response.success():
            logger.warning(
                "[Feishu] resource get failed: resource_key=%s, type=%s, code=%s, msg=%s, log_id=%s ",
                file_key,
                type,
                response.code,
                response.msg,
                response.get_log_id(),
            )
            return f"Failed to obtain the [{type}]"

        image_stream = getattr(response, "file", None)
        if image_stream is None:
            logger.warning("[Feishu] resource get returned no file stream: resource_key=%s, type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"

        try:
            content: bytes = await asyncio.to_thread(image_stream.read)
        except Exception:
            logger.exception("[Feishu] failed to read resource stream: resource_key=%s, type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"

        if not content:
            logger.warning("[Feishu] empty resource content: resource_key=%s, type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"

        paths = get_paths()
        effective_user_id = user_id or get_effective_user_id()
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)
        uploads_dir = paths.sandbox_uploads_dir(thread_id, user_id=effective_user_id).resolve()

        ext = "png" if type == "image" else "bin"
        raw_filename = getattr(response, "file_name", "") or f"feishu_{file_key[-12:]}.{ext}"

        # 保留扩展名，仅替换文件名部分的路径分隔符。
        if "." in raw_filename:
            name_part, ext = raw_filename.rsplit(".", 1)
            name_part = re.sub(r"[./\\]", "_", name_part)
            filename = f"{name_part}.{ext}"
        else:
            filename = re.sub(r"[./\\]", "_", raw_filename)
        resolved_target = uploads_dir / filename

        def down_load():
            """在文件锁保护下写入下载内容，避免并发覆盖同名文件。"""
            with self._thread_lock:
                resolved_target.write_bytes(content)

        try:
            await asyncio.to_thread(down_load)
        except Exception:
            logger.exception("[Feishu] failed to persist downloaded resource: %s, type=%s", resolved_target, type)
            return f"Failed to obtain the [{type}]"

        virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{resolved_target.name}"

        try:
            sandbox_provider = get_sandbox_provider()
            sandbox_id = sandbox_provider.acquire(thread_id, user_id=effective_user_id)
            if sandbox_id != "local":
                sandbox = sandbox_provider.get(sandbox_id)
                if sandbox is None:
                    logger.warning("[Feishu] sandbox not found for thread_id=%s", thread_id)
                    return f"Failed to obtain the [{type}]"
                sandbox.update_file(virtual_path, content)
        except Exception:
            logger.exception("[Feishu] failed to sync resource into non-local sandbox: %s", virtual_path)
            return f"Failed to obtain the [{type}]"

        logger.info("[Feishu] downloaded resource mapped: file_key=%s -> %s", file_key, virtual_path)
        return virtual_path

    # 消息格式化。

    @staticmethod
    def _build_card_content(text: str) -> str:
        """将 Markdown 正文封装为飞书交互卡片 JSON。"""
        card = {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "elements": [{"tag": "markdown", "content": text}],
        }
        return json.dumps(card)

    # 消息表情回应。

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """为指定消息添加表情回应；SDK 不可用或请求失败时仅记录日志。"""
        if not self._api_client or not self._CreateMessageReactionRequest:
            return
        try:
            request = self._CreateMessageReactionRequest.builder().message_id(message_id).request_body(self._CreateMessageReactionRequestBody.builder().reaction_type(self._Emoji.builder().emoji_type(emoji_type).build()).build()).build()
            await asyncio.to_thread(self._api_client.im.v1.message_reaction.create, request)
            logger.info("[Feishu] reaction '%s' added to message %s", emoji_type, message_id)
        except Exception:
            logger.exception("[Feishu] failed to add reaction '%s' to message %s", emoji_type, message_id)

    async def _reply_card(self, message_id: str, text: str) -> str | None:
        """以交互卡片回复指定消息，并返回新卡片的消息 ID。"""
        if not self._api_client:
            return None

        content = self._build_card_content(text)
        request = self._ReplyMessageRequest.builder().message_id(message_id).request_body(self._ReplyMessageRequestBody.builder().msg_type("interactive").content(content).build()).build()
        response = await asyncio.to_thread(self._api_client.im.v1.message.reply, request)
        response_data = getattr(response, "data", None)
        return getattr(response_data, "message_id", None)

    async def _create_card(self, chat_id: str, text: str) -> None:
        """在目标聊天中创建新的交互卡片消息。"""
        if not self._api_client:
            return

        content = self._build_card_content(text)
        request = self._CreateMessageRequest.builder().receive_id_type("chat_id").request_body(self._CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("interactive").content(content).build()).build()
        await asyncio.to_thread(self._api_client.im.v1.message.create, request)

    async def _update_card(self, message_id: str, text: str) -> None:
        """原位更新已有交互卡片的正文。"""
        if not self._api_client or not self._PatchMessageRequest:
            return

        content = self._build_card_content(text)
        request = self._PatchMessageRequest.builder().message_id(message_id).request_body(self._PatchMessageRequestBody.builder().content(content).build()).build()
        await asyncio.to_thread(self._api_client.im.v1.message.patch, request)

    def _track_background_task(self, task: asyncio.Task, *, name: str, msg_id: str) -> None:
        """保留后台任务引用，并在任务结束时统一清理和记录异常。"""
        self._background_tasks.add(task)
        task.add_done_callback(lambda done_task, task_name=name, mid=msg_id: self._finalize_background_task(done_task, task_name, mid))

    def _finalize_background_task(self, task: asyncio.Task, name: str, msg_id: str) -> None:
        """从后台任务集合移除已结束任务并读取其异常。"""
        self._background_tasks.discard(task)
        self._log_task_error(task, name, msg_id)

    async def _create_running_card(
        self,
        source_message_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """创建处理中卡片，并在飞书返回消息 ID 后缓存其与原消息的关联。"""
        running_card_id = await self._reply_card(source_message_id, self._compose_card_text(text, metadata))
        if running_card_id:
            self._running_card_ids[source_message_id] = running_card_id
            logger.info("[Feishu] running card created: source=%s card=%s", source_message_id, running_card_id)
        else:
            logger.warning("[Feishu] running card creation returned no message_id for source=%s, subsequent updates will fall back to new replies", source_message_id)
        return running_card_id

    def _ensure_running_card_started(
        self,
        source_message_id: str,
        text: str = "thinking...",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> asyncio.Task | None:
        """为原消息至多启动一个处理中卡片创建任务，并复用进行中的任务。"""
        running_card_id = self._running_card_ids.get(source_message_id)
        if running_card_id:
            return None

        running_card_task = self._running_card_tasks.get(source_message_id)
        if running_card_task:
            return running_card_task

        running_card_task = asyncio.create_task(self._create_running_card(source_message_id, text, metadata=metadata))
        self._running_card_tasks[source_message_id] = running_card_task
        running_card_task.add_done_callback(lambda done_task, mid=source_message_id: self._finalize_running_card_task(mid, done_task))
        return running_card_task

    def _finalize_running_card_task(self, source_message_id: str, task: asyncio.Task) -> None:
        """仅清除当前对应的卡片创建任务，并记录其执行异常。"""
        if self._running_card_tasks.get(source_message_id) is task:
            self._running_card_tasks.pop(source_message_id, None)
        self._log_task_error(task, "create_running_card", source_message_id)

    async def _ensure_running_card(
        self,
        source_message_id: str,
        text: str = "thinking...",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """获取现有处理中卡片 ID，或等待唯一的创建任务完成。"""
        running_card_id = self._running_card_ids.get(source_message_id)
        if running_card_id:
            return running_card_id

        running_card_task = self._ensure_running_card_started(
            source_message_id,
            text,
            metadata=metadata,
        )
        if running_card_task is None:
            return self._running_card_ids.get(source_message_id)
        return await running_card_task

    async def _send_running_reply(self, message_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        """尽力创建线程内的处理中卡片，失败时记录异常但不影响主处理流程。"""
        try:
            await self._ensure_running_card(message_id, metadata=metadata)
        except Exception:
            logger.exception("[Feishu] failed to send running reply for message %s", message_id)

    async def _send_card_message(self, msg: OutboundMessage) -> None:
        """创建或更新与原始消息关联的卡片，并在最终回复时清理进度状态。"""
        source_message_id = msg.thread_ts
        if source_message_id:
            running_card_id = self._running_card_ids.get(source_message_id)
            awaited_running_card_task = False

            if not running_card_id:
                running_card_task = self._running_card_tasks.get(source_message_id)
                if running_card_task:
                    awaited_running_card_task = True
                    running_card_id = await running_card_task

            if running_card_id:
                card_text = self._compose_card_text(msg.text, msg.metadata)
                try:
                    await self._update_card(running_card_id, card_text)
                except Exception:
                    if not msg.is_final:
                        raise
                    logger.exception(
                        "[Feishu] failed to patch running card %s, falling back to final reply",
                        running_card_id,
                    )
                    fallback_card_id = await self._reply_card(source_message_id, card_text)
                    self._remember_thread_mapping(msg, source_message_id, fallback_card_id)
                    self._remember_pending_clarification(msg, fallback_card_id)
                else:
                    self._remember_thread_mapping(msg, source_message_id, running_card_id)
                    self._remember_pending_clarification(msg, running_card_id)
                    logger.info("[Feishu] running card updated: source=%s card=%s", source_message_id, running_card_id)
            elif msg.is_final:
                final_card_id = await self._reply_card(
                    source_message_id,
                    self._compose_card_text(msg.text, msg.metadata),
                )
                self._remember_thread_mapping(msg, source_message_id, final_card_id)
                self._remember_pending_clarification(msg, final_card_id)
            elif awaited_running_card_task:
                logger.warning(
                    "[Feishu] running card task finished without message_id for source=%s, skipping duplicate non-final creation",
                    source_message_id,
                )
            else:
                created_card_id = await self._ensure_running_card(
                    source_message_id,
                    msg.text,
                    metadata=msg.metadata,
                )
                self._remember_thread_mapping(msg, source_message_id, created_card_id)

            if msg.is_final:
                self._running_card_ids.pop(source_message_id, None)
                await self._add_reaction(source_message_id, "DONE")
            return

        await self._create_card(msg.chat_id, msg.text)

    # 内部消息关联与异步任务。

    def _remember_thread_mapping(self, msg: OutboundMessage, *topic_ids: str | None) -> None:
        """保存 DeerFlow 线程与飞书话题/消息标识的映射。"""
        store = self.config.get("channel_store")
        if store is None or not msg.thread_id:
            return

        metadata_topic_ids = [
            msg.metadata.get("message_id"),
            msg.metadata.get("root_id"),
            msg.metadata.get("parent_id"),
            msg.metadata.get("thread_id"),
            msg.metadata.get("topic_id"),
        ]
        user_id = ""
        raw_user_id = msg.metadata.get("user_id")
        if isinstance(raw_user_id, str):
            user_id = raw_user_id

        seen: set[str] = set()
        for topic_id in [*topic_ids, *metadata_topic_ids]:
            topic_id = self._non_empty_str(topic_id)
            if not topic_id or topic_id in seen:
                continue
            seen.add(topic_id)
            try:
                store.set_thread_id(
                    self.name,
                    msg.chat_id,
                    msg.thread_id,
                    topic_id=topic_id,
                    user_id=user_id,
                )
            except Exception:
                logger.exception("[Feishu] failed to remember thread mapping for topic_id=%s", topic_id)

    def _remember_pending_clarification(self, msg: OutboundMessage, card_message_id: str | None) -> None:
        """缓存需要用户澄清的回复信息，以便后续普通消息继续对应会话。"""
        if not msg.is_final or msg.metadata.get(PENDING_CLARIFICATION_METADATA_KEY) is not True:
            return

        user_id = self._non_empty_str(msg.metadata.get("user_id"))
        topic_id = self._non_empty_str(msg.metadata.get("topic_id"))
        source_message_id = self._non_empty_str(msg.thread_ts) or self._non_empty_str(msg.metadata.get("message_id"))
        if not (user_id and topic_id and msg.thread_id and source_message_id and card_message_id):
            return

        key = self._pending_key(msg.chat_id, user_id)
        pending = {
            "thread_id": msg.thread_id,
            "topic_id": topic_id,
            "source_message_id": source_message_id,
            "card_message_id": card_message_id,
            "created_at": time.time(),
        }
        with self._thread_lock:
            # 普通文本没有回复标识时依赖短期内存提示；显式回复仍由持久化映射处理。
            self._pending_clarifications.setdefault(key, []).append(pending)
        logger.info(
            "[Feishu] pending clarification remembered: chat_id=%s user_id=%s topic_id=%s thread_id=%s",
            msg.chat_id,
            user_id,
            topic_id,
            msg.thread_id,
        )

    def _consume_pending_clarification(self, chat_id: str, user_id: str) -> dict[str, Any] | None:
        """取出该聊天用户最早且未过期的待澄清上下文。"""
        key = self._pending_key(chat_id, user_id)
        with self._thread_lock:
            pending_items = self._pending_clarifications.get(key)
            if not pending_items:
                return None

            now = time.time()
            while pending_items:
                pending = pending_items.pop(0)
                created_at = pending.get("created_at")
                if isinstance(created_at, (int, float)) and now - created_at <= PENDING_CLARIFICATION_TTL_SECONDS:
                    if pending_items:
                        self._pending_clarifications[key] = pending_items
                    else:
                        self._pending_clarifications.pop(key, None)
                    return pending
                logger.info("[Feishu] pending clarification expired: chat_id=%s user_id=%s", chat_id, user_id)

            self._pending_clarifications.pop(key, None)
            return None

    def _ensure_pending_thread_mapping(self, chat_id: str, user_id: str, pending: dict[str, Any]) -> None:
        """将待澄清上下文中的话题重新绑定到原 DeerFlow 线程。"""
        store = self.config.get("channel_store")
        topic_id = self._non_empty_str(pending.get("topic_id"))
        thread_id = self._non_empty_str(pending.get("thread_id"))
        if store is None or not topic_id or not thread_id:
            return
        try:
            store.set_thread_id(self.name, chat_id, thread_id, topic_id=topic_id, user_id=user_id)
        except Exception:
            logger.exception("[Feishu] failed to restore pending clarification mapping for topic_id=%s", topic_id)

    def _resolve_topic_id(
        self,
        chat_id: str,
        msg_id: str,
        *,
        root_id: str | None,
        parent_id: str | None,
        thread_id: str | None,
    ) -> tuple[str, bool]:
        """根据已保存的话题映射选择会话标识，并指出是否命中已有线程。"""
        store = self.config.get("channel_store")
        candidates = [root_id, parent_id, thread_id]

        if store is not None:
            for candidate in candidates:
                candidate = self._non_empty_str(candidate)
                if not candidate:
                    continue
                try:
                    if store.get_thread_id(self.name, chat_id, topic_id=candidate):
                        return candidate, True
                except Exception:
                    logger.exception("[Feishu] failed to resolve stored topic mapping for topic_id=%s", candidate)

        return root_id or msg_id, False

    @staticmethod
    def _is_batchable_file_inbound(
        *,
        msg_type: InboundMessageType,
        text: str,
        files: list[dict[str, Any]],
        root_id: str | None,
        parent_id: str | None,
        thread_id: str | None,
    ) -> bool:
        """判断单个无话题上下文的图片或文件消息是否可参与短窗口合并。"""
        return msg_type == InboundMessageType.CHAT and text in {"[file]", "[image]"} and len(files) == 1 and not (root_id or parent_id or thread_id)

    def _schedule_prepare_inbound(
        self,
        msg_id: str,
        inbound: InboundMessage,
        *,
        source_message_ids: list[str] | None = None,
    ) -> None:
        """将入站消息准备工作安全调度到通道主事件循环。"""
        if self._main_loop and self._main_loop.is_running():
            logger.info("[Feishu] publishing inbound message to bus (type=%s, msg_id=%s)", inbound.msg_type.value, msg_id)
            fut = asyncio.run_coroutine_threadsafe(
                self._prepare_inbound(msg_id, inbound, source_message_ids=source_message_ids),
                self._main_loop,
            )
            fut.add_done_callback(lambda f, mid=msg_id: self._log_future_error(f, "prepare_inbound", mid))
        else:
            logger.warning("[Feishu] main loop not running, cannot publish inbound message")

    def _schedule_batch_flush(self, key: tuple[str, str], source_message_id: str) -> None:
        """在主事件循环安排入站文件批次的延迟提交。"""
        if self._main_loop and self._main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._flush_pending_inbound_batch_after(key, source_message_id), self._main_loop)
            fut.add_done_callback(lambda f, mid=source_message_id: self._log_future_error(f, "flush_inbound_batch", mid))
        else:
            logger.warning("[Feishu] main loop not running, cannot flush inbound batch")

    def _queue_file_inbound_batch(self, msg_id: str, inbound: InboundMessage) -> bool:
        """合并同一用户短时间连续发送的文件消息，并安排批次刷新。"""
        key = self._pending_key(inbound.chat_id, inbound.user_id)
        should_schedule_flush = False
        expired_batch: tuple[str, InboundMessage, list[str]] | None = None

        with self._thread_lock:
            batch = self._pending_inbound_batches.get(key)
            now = time.time()
            if batch:
                if now - batch["created_at"] <= FEISHU_INBOUND_BATCH_WINDOW_SECONDS:
                    batched_inbound = batch["inbound"]
                    batch["message_ids"].append(msg_id)
                    batch["text_parts"].append(inbound.text)
                    batched_inbound.text = "\n\n".join(part for part in batch["text_parts"] if part)
                    batched_inbound.files.extend(inbound.files)
                    batched_inbound.metadata["batched_message_ids"] = list(batch["message_ids"])
                    logger.info(
                        "[Feishu] batched inbound file message: chat_id=%s user_id=%s anchor=%s msg_id=%s files=%d",
                        inbound.chat_id,
                        inbound.user_id,
                        batch["anchor_message_id"],
                        msg_id,
                        len(batched_inbound.files),
                    )
                    return True

                expired_batch = (batch["anchor_message_id"], batch["inbound"], list(batch["message_ids"]))

            self._pending_inbound_batches[key] = {
                "anchor_message_id": msg_id,
                "created_at": now,
                "inbound": inbound,
                "message_ids": [msg_id],
                "text_parts": [inbound.text],
            }
            inbound.metadata["batched_message_ids"] = [msg_id]
            should_schedule_flush = True

        if should_schedule_flush:
            self._schedule_batch_flush(key, msg_id)
        if expired_batch:
            anchor_message_id, expired_inbound, source_message_ids = expired_batch
            self._schedule_prepare_inbound(anchor_message_id, expired_inbound, source_message_ids=source_message_ids)
        return True

    def _pop_pending_inbound_batch(self, key: tuple[str, str], *, anchor_message_id: str | None = None) -> tuple[str, InboundMessage, list[str]] | None:
        """原子取出待发送批次；可限制只能取出指定锚点对应的批次。"""
        with self._thread_lock:
            batch = self._pending_inbound_batches.get(key)
            if not batch:
                return None
            if anchor_message_id is not None and batch["anchor_message_id"] != anchor_message_id:
                return None
            self._pending_inbound_batches.pop(key, None)
            return batch["anchor_message_id"], batch["inbound"], list(batch["message_ids"])

    async def _flush_pending_inbound_batch_after(self, key: tuple[str, str], anchor_message_id: str) -> None:
        """等待合并窗口结束后取出批次，并将合并消息发布到处理流程。"""
        await asyncio.sleep(FEISHU_INBOUND_BATCH_WINDOW_SECONDS)
        batch = self._pop_pending_inbound_batch(key, anchor_message_id=anchor_message_id)
        if not batch:
            return
        anchor_message_id, inbound, source_message_ids = batch
        logger.info(
            "[Feishu] flushing inbound file batch: chat_id=%s user_id=%s anchor=%s messages=%d files=%d",
            inbound.chat_id,
            inbound.user_id,
            anchor_message_id,
            len(source_message_ids),
            len(inbound.files),
        )
        await self._prepare_inbound(anchor_message_id, inbound, source_message_ids=source_message_ids)

    @staticmethod
    def _log_task_error(task: asyncio.Task, name: str, msg_id: str) -> None:
        """读取后台任务异常并记录失败或取消状态。"""
        try:
            exc = task.exception()
            if exc:
                logger.error("[Feishu] %s failed for msg_id=%s: %s", name, msg_id, exc)
        except asyncio.CancelledError:
            logger.info("[Feishu] %s cancelled for msg_id=%s", name, msg_id)
        except Exception:
            pass

    async def _prepare_inbound(self, msg_id: str, inbound, *, source_message_ids: list[str] | None = None) -> None:
        """补充连接身份、异步添加消息回应并启动处理中卡片后发布入站消息。"""
        inbound = await self._attach_connection_identity(inbound)
        reaction_message_ids = source_message_ids or [msg_id]
        for reaction_message_id in reaction_message_ids:
            reaction_task = asyncio.create_task(self._add_reaction(reaction_message_id, "OK"))
            self._track_background_task(reaction_task, name="add_reaction", msg_id=reaction_message_id)
        self._ensure_running_card_started(msg_id, metadata=inbound.metadata)
        await self.bus.publish_inbound(inbound)

    async def _attach_connection_identity(self, inbound: InboundMessage) -> InboundMessage:
        """根据飞书连接记录将已认证的 DeerFlow 所有者身份附加到入站消息。"""
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="feishu",
            workspace_id=inbound.chat_id,
        )

    async def _bind_connection_from_connect_code(self, *, message_id: str, chat_id: str, user_id: str, code: str) -> bool:
        """消费一次性连接码并绑定飞书账号；已处理连接码的请求返回 True。"""
        if self._connection_repo is None or not code:
            return False

        state = await self._connection_repo.consume_oauth_state(provider="feishu", state=code)
        if state is None:
            await self._reply_card(message_id, "Feishu connection code is invalid or expired.")
            return True

        if not user_id or not chat_id:
            await self._reply_card(message_id, "Feishu connection could not be completed from this message.")
            return True

        await self._connection_repo.upsert_connection(
            owner_user_id=state["owner_user_id"],
            provider="feishu",
            external_account_id=user_id,
            workspace_id=chat_id,
            metadata={
                "chat_id": chat_id,
                "message_id": message_id,
            },
            status="connected",
        )
        await self._reply_card(message_id, "Feishu connected to DeerFlow.")
        return True

    def _on_message(self, event) -> None:
        """解析飞书回调消息、关联线程并将文本或附件事件送入消息总线。"""
        try:
            logger.info("[Feishu] raw event received: type=%s", type(event).__name__)
            message = event.event.message
            chat_id = message.chat_id
            msg_id = message.message_id
            sender_id = event.event.sender.sender_id.open_id

            root_id = getattr(message, "root_id", None) or None
            chat_type = getattr(message, "chat_type", None)
            parent_id = self._non_empty_str(getattr(message, "parent_id", None))
            feishu_thread_id = self._non_empty_str(getattr(message, "thread_id", None))

            # 解析飞书消息正文。
            content = json.loads(message.content)

            # 记录后续下载所需的资源键；图片键与普通文件键分开，文件键也涵盖视频和音频。
            files_list = []

            if "text" in content:
                # 普通文本消息。
                text = content["text"]
            elif "file_key" in content:
                file_key = content.get("file_key")
                if isinstance(file_key, str) and file_key:
                    files_list.append({"file_key": file_key})
                    text = "[file]"
                else:
                    text = ""
            elif "image_key" in content:
                image_key = content.get("image_key")
                if isinstance(image_key, str) and image_key:
                    files_list.append({"image_key": image_key})
                    text = "[image]"
                else:
                    text = ""
            elif "content" in content and isinstance(content["content"], list):
                # 处理话题组或帖子等以 content 列表表示的富文本消息。
                text_paragraphs: list[str] = []
                for paragraph in content["content"]:
                    if isinstance(paragraph, list):
                        paragraph_text_parts: list[str] = []
                        for element in paragraph:
                            if isinstance(element, dict):
                                # 保留普通文本和 @ 提及内容。
                                if element.get("tag") in ("text", "at"):
                                    text_value = element.get("text", "")
                                    if text_value:
                                        paragraph_text_parts.append(text_value)
                                elif element.get("tag") == "img":
                                    image_key = element.get("image_key")
                                    if isinstance(image_key, str) and image_key:
                                        files_list.append({"image_key": image_key})
                                        paragraph_text_parts.append("[image]")
                                elif element.get("tag") in ("file", "media"):
                                    file_key = element.get("file_key")
                                    if isinstance(file_key, str) and file_key:
                                        files_list.append({"file_key": file_key})
                                        paragraph_text_parts.append("[file]")
                        if paragraph_text_parts:
                            # 段落内片段以空格分隔，避免相邻文本粘连。
                            text_paragraphs.append(" ".join(paragraph_text_parts))

                # 段落间保留空行，避免丢失原有边界。
                text = "\n\n".join(text_paragraphs)
            else:
                text = ""
            text = text.strip()

            logger.info(
                "[Feishu] parsed message: chat_id=%s, msg_id=%s, root_id=%s, parent_id=%s, thread_id=%s, chat_type=%s, sender=%s, text_len=%d",
                chat_id,
                msg_id,
                root_id,
                parent_id,
                feishu_thread_id,
                chat_type,
                sender_id,
                len(text or ""),
            )

            if not (text or files_list):
                logger.info("[Feishu] empty text, ignoring message")
                return

            connect_code = self._pending_connect_code(text)
            if connect_code:
                if self._main_loop and self._main_loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(
                        self._bind_connection_from_connect_code(
                            message_id=msg_id,
                            chat_id=chat_id,
                            user_id=sender_id,
                            code=connect_code,
                        ),
                        self._main_loop,
                    )
                    fut.add_done_callback(lambda f, mid=msg_id: self._log_future_error(f, "bind_connection", mid))
                else:
                    logger.warning("[Feishu] main loop not running, cannot bind channel connection")
                return

            # 只有已知命令才按命令处理；绝对路径等其他斜杠开头文本仍作为普通对话。
            if _is_feishu_command(text):
                msg_type = InboundMessageType.COMMAND
            else:
                msg_type = InboundMessageType.CHAT

            # topic_id 决定消息映射到哪个 LangGraph 线程。私聊默认共用一个线程，
            # 但先查已保存映射，以兼容升级前创建的私聊线程。
            topic_id, resolved_from_stored_mapping = self._resolve_topic_id(
                chat_id,
                msg_id,
                root_id=root_id,
                parent_id=parent_id,
                thread_id=feishu_thread_id,
            )
            if chat_type == "p2p" and not resolved_from_stored_mapping:
                topic_id = None
            resolved_from_pending = False
            if msg_type == InboundMessageType.CHAT and not resolved_from_stored_mapping:
                pending = self._consume_pending_clarification(chat_id, sender_id)
                pending_topic_id = self._non_empty_str(pending.get("topic_id")) if pending else None
                if pending_topic_id:
                    topic_id = pending_topic_id
                    self._ensure_pending_thread_mapping(chat_id, sender_id, pending)
                    resolved_from_pending = True

            source_preview = None
            if self._should_include_source_preview(
                chat_type=chat_type,
                root_id=root_id,
                parent_id=parent_id,
                thread_id=feishu_thread_id,
            ):
                source_preview = self._compact_source_preview(text)

            metadata = {
                "message_id": msg_id,
                "root_id": root_id,
                "parent_id": parent_id,
                "thread_id": feishu_thread_id,
                "topic_id": topic_id,
                "user_id": sender_id,
                RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY: resolved_from_pending,
            }
            if source_preview:
                metadata[SOURCE_PREVIEW_METADATA_KEY] = source_preview

            inbound = self._make_inbound(
                chat_id=chat_id,
                user_id=sender_id,
                text=text,
                msg_type=msg_type,
                thread_ts=msg_id,
                files=files_list,
                metadata=metadata,
            )
            inbound.topic_id = topic_id

            if self._is_batchable_file_inbound(
                msg_type=msg_type,
                text=text,
                files=files_list,
                root_id=root_id,
                parent_id=parent_id,
                thread_id=feishu_thread_id,
            ):
                self._queue_file_inbound_batch(msg_id, inbound)
                return

            self._schedule_prepare_inbound(msg_id, inbound)
        except Exception:
            logger.exception("[Feishu] error processing message")
