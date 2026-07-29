"""集中定义所有即时通讯通道共享的控制命令。

权威命令集合只维护在此处，使平台解析器与 ``ChannelManager`` 的分发判断始终一致；
新增或移除命令时无需同步修改多个通道实现。
"""

from __future__ import annotations

KNOWN_CHANNEL_COMMANDS: frozenset[str] = frozenset(
    {
        "/bootstrap",
        "/goal",
        "/new",
        "/status",
        "/models",
        "/memory",
        "/help",
    }
)


def extract_connect_code(text: str) -> str | None:
    """从连接命令中提取一次性绑定码，不接受缺少参数的命令。"""
    parts = text.strip().split()
    if len(parts) < 2:
        return None
    command = parts[0].lower()
    if command in {"/connect", "connect"}:
        return parts[1]
    return None


def is_known_channel_command(text: str) -> bool:
    """判断文本首段是否为已注册的通道控制命令。"""
    if not text.startswith("/"):
        return False
    return text.split(maxsplit=1)[0].lower() in KNOWN_CHANNEL_COMMANDS
