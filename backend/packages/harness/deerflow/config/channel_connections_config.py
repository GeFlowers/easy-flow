'''配置即时通信账号绑定流程及各通道的连接状态。'''

from __future__ import annotations

from pydantic import BaseModel, Field


class BindingCodeChannelConnectionConfig(BaseModel):
    '''记录一种即时通信提供者的绑定功能是否开放。'''

    enabled: bool = False

    @property
    def configured(self) -> bool:
        '''告知绑定码连接器无需独立凭据即可完成配置。'''
        return True


class ChannelConnectionsConfig(BaseModel):
    '''汇总通道绑定开关、身份绑定要求和各提供者状态。'''

    enabled: bool = False
    require_bound_identity: bool = True
    wechat: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    wecom: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)

    def provider_status(self, provider: str) -> dict[str, bool]:
        '''返回指定通道是否启用且具备连接配置。'''
        config = getattr(self, provider, None)
        if config is None:
            return {"enabled": False, "configured": False}
        enabled = bool(config.enabled)
        return {
            "enabled": enabled,
            "configured": enabled and bool(config.configured),
        }
