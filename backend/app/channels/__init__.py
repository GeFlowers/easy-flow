'''汇总 DeerFlow 即时通讯通道集成的公共接口。

可插拔通道通过 ``ChannelManager`` 把 Feishu/Lark、Slack、Telegram 等外部平台
连接到 DeerFlow Agent；管理器使用 ``langgraph-sdk`` 调用 Gateway 提供的
LangGraph-compatible API。
'''

from app.channels.base import Channel
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage

__all__ = [
    "Channel",
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
]
