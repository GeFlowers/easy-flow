'''定义所有即时通讯通道共同遵循的抽象契约。'''

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from concurrent.futures import CancelledError as FutureCancelledError
from typing import Any, TypeVar

from app.channels.commands import extract_connect_code
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Channel(ABC):
    '''统一外部即时通讯平台与内部消息总线之间的适配边界。

    每个通道负责把平台入站事件转换为 ``InboundMessage``，并把消息总线产生的
    ``OutboundMessage`` 发送回对应平台。子类必须实现 ``start``、``stop`` 和
    ``send``，文件收发与连接绑定等能力则可按平台特性选择性覆盖。
    '''

    def __init__(self, name: str, bus: MessageBus, config: dict[str, Any]) -> None:
        '''保存通道身份、共享总线及该平台的运行配置。'''
        self.name = name
        self.bus = bus
        self.config = config
        self._running = False
        self._connection_repo: Any = config.get("connection_repo")

    @property
    def is_running(self) -> bool:
        '''返回通道是否已进入运行状态。'''
        return self._running

    @property
    def supports_streaming(self) -> bool:
        '''声明通道是否能原地呈现增量回复，默认关闭该能力。'''
        return False

    # -- 生命周期 ----------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        '''启动外部平台的消息监听与出站订阅。'''

    @abstractmethod
    async def stop(self) -> None:
        '''停止监听并释放平台客户端等运行资源。'''

    # -- 出站消息 ----------------------------------------------------------

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        '''把出站消息发送到外部平台的目标会话。

        实现必须联合使用 ``msg.chat_id`` 与 ``msg.thread_ts`` 定位平台会话，
        避免同一聊天中的不同话题相互串扰。
        '''

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        '''上传单个附件；不支持文件能力的通道保持默认失败结果。

        返回值用于区分“不支持或上传失败”与成功发送，调用方据此记录告警，
        但不会让一个附件失败中断其余出站处理。
        '''
        return False

    # -- 共享辅助逻辑 ------------------------------------------------------

    async def _send_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        max_retries: int,
        log_prefix: str | None = None,
        operation_name: str = "send",
    ) -> T:
        '''按统一的指数退避策略执行可重试的出站操作。'''
        prefix = log_prefix or f"[{self.name}]"
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await operation()
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = 2**attempt
                    logger.warning(
                        "%s %s failed (attempt %d/%d), retrying in %ds: %s",
                        prefix,
                        operation_name,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.error("%s %s failed after %d attempts: %s", prefix, operation_name, max_retries, last_exc)
        if last_exc is None:
            raise RuntimeError(f"{self.name} {operation_name} failed without an exception from any attempt")
        raise last_exc

    def _log_future_error(self, fut: Any, name: str, msg_id: Any) -> None:
        '''检查由通道工作线程提交的 Future，并集中记录后台异常。'''
        try:
            exc = fut.exception()
        except (asyncio.CancelledError, FutureCancelledError, asyncio.InvalidStateError):
            return
        except Exception:
            logger.exception("[%s] failed to inspect future for %s (msg_id=%s)", self.name, name, msg_id)
            return

        if exc:
            logger.error("[%s] %s failed for msg_id=%s: %s", self.name, name, msg_id, exc)

    def _pending_connect_code(self, text: str) -> str | None:
        '''在启用连接仓库时提取 ``/connect <code>`` 中的一次性绑定码。

        平台适配器必须先检查绑定命令，再执行 ``allowed_users`` 或
        ``_check_user`` 校验。否则尚未被机器人识别的外部身份无法通过浏览器发起的
        首次绑定。Telegram 使用 ``/start <token>`` 深链流程，不经过此入口。
        '''
        if self._connection_repo is None:
            return None
        return extract_connect_code(text)

    def _make_inbound(
        self,
        chat_id: str,
        user_id: str,
        text: str,
        *,
        msg_type: InboundMessageType = InboundMessageType.CHAT,
        thread_ts: str | None = None,
        files: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> InboundMessage:
        '''按当前通道身份构造字段完整且集合字段互不共享的入站消息。'''
        return InboundMessage(
            channel_name=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            thread_ts=thread_ts,
            files=files or [],
            metadata=metadata or {},
        )

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        '''接收消息总线回调，并仅转发属于当前通道的出站消息。

        文本必须先于附件发送；若文本发送失败，则跳过全部附件，避免用户只收到
        缺少上下文的孤立文件。单个附件失败只记录告警，不影响后续附件。
        '''
        if msg.channel_name == self.name:
            try:
                await self.send(msg)
            except Exception:
                logger.exception("Failed to send outbound message on channel %s", self.name)
                # 附件必须依附于文本上下文，不能在主消息失败后单独投递。
                return

            for attachment in msg.attachments:
                try:
                    success = await self.send_file(msg, attachment)
                    if not success:
                        logger.warning("[%s] file upload skipped for %s", self.name, attachment.filename)
                except Exception:
                    logger.exception("[%s] failed to upload file %s", self.name, attachment.filename)

    async def receive_file(self, msg: InboundMessage, thread_id: str, *, user_id: str | None = None) -> InboundMessage:
        '''按通道能力把入站附件实体化到对应用户和线程的存储空间。

        默认实现保持消息不变。支持文件的子类可下载 ``msg.files`` 引用的远端内容，
        并把沙箱路径写入消息文本，使后续模型能够读取。``thread_id`` 与 ``user_id``
        共同限定存储边界，不能只依赖平台文件名定位目标。
        '''
        del user_id
        return msg
