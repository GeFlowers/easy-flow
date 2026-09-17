"""提供配置、channel、connections、配置相关功能。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SlackChannelConnectionConfig(BaseModel):
    """\u6267\u884c SlackChannelConnectionConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = False

    @property
    def configured(self) -> bool:
        """\u6267\u884c configured \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return True


class TelegramChannelConnectionConfig(BaseModel):
    """\u6267\u884c TelegramChannelConnectionConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = False
    bot_username: str = ""

    @property
    def configured(self) -> bool:
        """\u6267\u884c configured \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return bool(self.bot_username)


class DiscordChannelConnectionConfig(BaseModel):
    """\u6267\u884c DiscordChannelConnectionConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = False

    @property
    def configured(self) -> bool:
        """\u6267\u884c configured \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return True


class BindingCodeChannelConnectionConfig(BaseModel):
    """\u6267\u884c BindingCodeChannelConnectionConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = False

    @property
    def configured(self) -> bool:
        """\u6267\u884c configured \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return True


class ChannelConnectionsConfig(BaseModel):
    """\u6267\u884c ChannelConnectionsConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = False
    require_bound_identity: bool = True
    slack: SlackChannelConnectionConfig = Field(default_factory=SlackChannelConnectionConfig)
    telegram: TelegramChannelConnectionConfig = Field(default_factory=TelegramChannelConnectionConfig)
    discord: DiscordChannelConnectionConfig = Field(default_factory=DiscordChannelConnectionConfig)
    feishu: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    dingtalk: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    wechat: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    wecom: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)

    def provider_status(self, provider: str) -> dict[str, bool]:
        """\u6267\u884c provider_status \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        config = getattr(self, provider, None)
        if config is None:
            return {"enabled": False, "configured": False}
        enabled = bool(config.enabled)
        return {
            "enabled": enabled,
            "configured": enabled and bool(config.configured),
        }
