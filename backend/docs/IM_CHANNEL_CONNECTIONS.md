# 微信消息通道

目前消息平台接入仅包含个人微信（iLink）和企业微信。两者分别由 `wechat.py` 与 `wecom.py` 实现，并共用通道管理、消息总线、身份绑定和会话分发基础设施。

## 配置

在 `config.yaml` 的 `channels` 中启用所需平台：

```yaml
channels:
  wechat:
    enabled: true
    bot_token: $WECHAT_BOT_TOKEN
    ilink_bot_id: $WECHAT_ILINK_BOT_ID
  wecom:
    enabled: true
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET
```

也可以在工作区的通道设置中录入凭据并启动平台。用户连接记录由连接接口持久化；平台消息进入共用消息总线后，由 `ChannelManager` 创建或续接会话并回传回复。

## 代码边界

- `app/channels/providers/wechat.py`：个人微信 iLink 的认证、长轮询、消息转换和收发。
- `app/channels/providers/wecom.py`：企业微信机器人的 WebSocket（WebSocket，网页套接字）连接、消息转换和收发。
- `app/channels/service.py`：只注册和启动上述两种平台。
- `app/gateway/routers/integrations/channel_connections.py`：提供平台连接、凭据和用户绑定接口。

消息总线、通道管理器和连接存储是两种平台共用的基础设施，不属于平台适配器。
