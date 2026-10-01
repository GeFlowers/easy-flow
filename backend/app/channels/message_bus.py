'''提供解耦即时通讯通道与 Agent 调度器的异步发布订阅总线。'''

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PENDING_CLARIFICATION_METADATA_KEY = "pending_clarification"
RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY = "resolved_from_pending_clarification"


# 消息类型


class InboundMessageType(StrEnum):
    '''区分进入调度器的普通对话与控制命令。'''

    CHAT = "chat"
    COMMAND = "command"


@dataclass
class InboundMessage:
    '''承载外部即时通讯平台发往 Agent 调度器的标准化消息。

    ``user_id`` 始终表示平台用户，而 ``owner_user_id`` 表示 DeerFlow 内的资源
    所有者，两者不可混用。``topic_id`` 用于把同一平台话题映射到稳定的 DeerFlow
    线程；存在 ``connection_id`` 时，映射还会按用户拥有的连接隔离。
    '''

    channel_name: str
    chat_id: str
    user_id: str
    text: str
    msg_type: InboundMessageType = InboundMessageType.CHAT
    thread_ts: str | None = None
    topic_id: str | None = None
    connection_id: str | None = None
    owner_user_id: str | None = None
    workspace_id: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class ResolvedAttachment:
    '''表示已安全解析到宿主机路径、可以交给平台上传的附件。

    同时保留沙箱虚拟路径与宿主机真实路径，前者用于面向用户展示，后者仅供受控的
    上传实现读取，避免把内部文件系统布局泄露到消息正文。
    '''

    virtual_path: str
    actual_path: Path
    filename: str
    mime_type: str
    size: int
    is_image: bool


@dataclass
class OutboundMessage:
    '''承载 Agent 调度器发回外部通道的标准化消息。

    ``channel_name`` 和平台会话字段负责外部路由，``thread_id`` 标识产生回复的
    DeerFlow 上下文；``is_final`` 让支持流式更新的平台区分中间快照与最终结果。
    '''

    channel_name: str
    chat_id: str
    thread_id: str
    text: str
    artifacts: list[str] = field(default_factory=list)
    attachments: list[ResolvedAttachment] = field(default_factory=list)
    is_final: bool = True
    thread_ts: str | None = None
    connection_id: str | None = None
    owner_user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


# 消息总线

OutboundCallback = Callable[[OutboundMessage], Coroutine[Any, Any, None]]


class MessageBus:
    '''连接平台通道与 Agent 调度器的进程内异步发布订阅中心。

    入站方向使用单一队列，由调度器按到达顺序消费；出站方向使用监听器列表，
    让每个通道自行过滤目标消息。该对象不承担持久化，进程重启后的恢复由更上层
    的线程与运行存储负责。
    '''

    def __init__(self) -> None:
        '''初始化入站队列和无订阅者的出站监听器集合。'''
        self._inbound_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound_listeners: list[OutboundCallback] = []

    # -- 入站方向 ----------------------------------------------------------

    async def publish_inbound(self, msg: InboundMessage) -> None:
        '''把通道产生的入站消息加入调度器消费队列。'''
        await self._inbound_queue.put(msg)
        logger.info(
            "[Bus] inbound enqueued: channel=%s, chat_id=%s, type=%s, queue_size=%d",
            msg.channel_name,
            msg.chat_id,
            msg.msg_type.value,
            self._inbound_queue.qsize(),
        )

    async def get_inbound(self) -> InboundMessage:
        '''异步等待并取出下一条入站消息。'''
        return await self._inbound_queue.get()

    @property
    def inbound_queue(self) -> asyncio.Queue[InboundMessage]:
        '''暴露同一队列实例，供需要直接观察或消费队列的生命周期代码使用。'''
        return self._inbound_queue

    # -- 出站方向 ----------------------------------------------------------

    def subscribe_outbound(self, callback: OutboundCallback) -> None:
        '''注册接收全部出站消息的异步监听器。'''
        self._outbound_listeners.append(callback)

    def unsubscribe_outbound(self, callback: OutboundCallback) -> None:
        '''移除已注册的出站监听器，并保持其余监听器顺序不变。'''
        self._outbound_listeners = [cb for cb in self._outbound_listeners if cb != callback]

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        '''依次通知出站监听器，并隔离单个通道回调的异常。'''
        logger.info(
            "[Bus] outbound dispatching: channel=%s, chat_id=%s, listeners=%d, text_len=%d",
            msg.channel_name,
            msg.chat_id,
            len(self._outbound_listeners),
            len(msg.text),
        )
        for callback in self._outbound_listeners:
            try:
                await callback(msg)
            except Exception:
                logger.exception("Error in outbound callback for channel=%s", msg.channel_name)
