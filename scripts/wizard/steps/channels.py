"""实现配置向导的消息渠道连接步骤。"""

from __future__ import annotations

from dataclasses import dataclass

from wizard.ui import ask_multi_choice, print_header, print_info, print_success


CHANNEL_CONNECTION_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("telegram", "Telegram", "direct messages through your DeerFlow bot"),
    ("slack", "Slack", "workspace messages and mentions"),
    ("discord", "Discord", "server messages through your DeerFlow bot"),
    ("feishu", "Feishu / Lark", "messages through your DeerFlow app"),
    ("dingtalk", "DingTalk", "Stream Push messages through your DeerFlow bot"),
    ("wechat", "WeChat", "iLink messages through your DeerFlow bot"),
    ("wecom", "WeCom", "messages through your DeerFlow AI bot"),
)


@dataclass
class ChannelConnectionsStepResult:
    """记录消息渠道连接步骤中启用的服务商。"""
    enabled_providers: list[str]


def run_channels_step(step_label: str = "Step 4/5") -> ChannelConnectionsStepResult:
    """执行运行对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    print_header(f"{step_label} · IM Channels (optional)")
    print_info("Choose which IM channels should appear in the DeerFlow sidebar and Settings.")
    print_info("Credentials can be entered later from the browser with Connect or Modify.")
    print()

    options = [f"{display_name}  —  {description}" for _, display_name, description in CHANNEL_CONNECTION_OPTIONS]
    selected = ask_multi_choice(
        "Enable channels (comma-separated numbers, 'all', or Enter for none)",
        options,
        default=[],
    )
    enabled_providers = [CHANNEL_CONNECTION_OPTIONS[idx][0] for idx in selected]

    if enabled_providers:
        display_names = [CHANNEL_CONNECTION_OPTIONS[idx][1] for idx in selected]
        print_success(f"Enabled channels: {', '.join(display_names)}")
    else:
        print_info("No IM channels selected; channel connections will stay disabled.")

    return ChannelConnectionsStepResult(enabled_providers=enabled_providers)
