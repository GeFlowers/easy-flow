"""注册飞书通道专用的逐运行策略。"""

from __future__ import annotations

from app.channels.run_policy import CHANNEL_RUN_POLICY, ChannelRunPolicy


def register_policy() -> None:
    """启用飞书同一 DeerFlow 线程内的回合排队。"""
    CHANNEL_RUN_POLICY["feishu"] = ChannelRunPolicy(
        serialize_thread_runs=True,
    )


register_policy()
