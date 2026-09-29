"""管理全部即时通讯通道及其共享调度器的生命周期。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from app.channels.base import Channel
from app.channels.manager import DEFAULT_GATEWAY_URL, DEFAULT_LANGGRAPH_URL, ChannelManager
from app.channels.message_bus import MessageBus
from app.channels.runtime_config_store import merge_runtime_channel_configs
from app.channels.store import ChannelStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.channel_connections_config import ChannelConnectionsConfig

# 通道类按需导入，未启用的平台不会加载其可选 SDK。
_CHANNEL_REGISTRY: dict[str, str] = {
    "dingtalk": "app.channels.providers.dingtalk:DingTalkChannel",
    "discord": "app.channels.providers.discord:DiscordChannel",
    "feishu": "app.channels.providers.feishu:FeishuChannel",
    "github": "app.channels.providers.github:GitHubChannel",
    "slack": "app.channels.providers.slack:SlackChannel",
    "telegram": "app.channels.providers.telegram:TelegramChannel",
    "wechat": "app.channels.providers.wechat:WechatChannel",
    "wecom": "app.channels.providers.wecom:WeComChannel",
}

# 这些键只用于判断“已配置但未启用”，不会参与凭据有效性校验。
_CHANNEL_CREDENTIAL_KEYS: dict[str, list[str]] = {
    "dingtalk": ["client_id", "client_secret"],
    "discord": ["bot_token"],
    "feishu": ["app_id", "app_secret"],
    "slack": ["bot_token", "app_token"],
    "telegram": ["bot_token"],
    "wecom": ["bot_id", "bot_secret"],
    "wechat": ["bot_token"],
}

_CHANNELS_LANGGRAPH_URL_ENV = "DEER_FLOW_CHANNELS_LANGGRAPH_URL"
_CHANNELS_GATEWAY_URL_ENV = "DEER_FLOW_CHANNELS_GATEWAY_URL"


def _channel_has_credentials(name: str, channel_config: dict[str, Any]) -> bool:
    """判断通道是否至少填写了一个非布尔凭据字段。"""
    cred_keys = _CHANNEL_CREDENTIAL_KEYS.get(name, [])
    return any(not isinstance(channel_config.get(key), bool) and channel_config.get(key) is not None and str(channel_config[key]).strip() for key in cred_keys)


def _resolve_service_url(config: dict[str, Any], config_key: str, env_key: str, default: str) -> str:
    """按通道配置、环境变量、默认值的顺序解析服务地址。"""
    value = config.pop(config_key, None)
    if isinstance(value, str) and value.strip():
        return value
    env_value = os.getenv(env_key, "").strip()
    if env_value:
        return env_value
    return default


def _merge_channel_connection_runtime_config(channels_config: dict[str, Any], app_config: AppConfig) -> None:
    """把界面持久化的运行时连接覆盖合并到静态通道配置。"""
    connection_config = getattr(app_config, "channel_connections", None)
    merge_runtime_channel_configs(channels_config, connection_config)


def _make_connection_repo(connection_config: ChannelConnectionsConfig | None):
    """在连接功能和数据库均可用时创建连接仓库。"""
    if connection_config is None or not getattr(connection_config, "enabled", False):
        return None

    try:
        from deerflow.persistence.channel_connections import ChannelConnectionRepository
        from deerflow.persistence.engine import get_session_factory
    except Exception:
        logger.exception("Failed to import channel connection repository")
        return None

    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("Channel connections are enabled but database persistence is not available")
        return None
    return ChannelConnectionRepository(session_factory)


class ChannelService:
    """统一管理配置中的通道实例与共享 ``ChannelManager``。

    服务读取 ``config.yaml`` 的 ``channels`` 配置及运行时覆盖，只实例化已启用通道，
    并确保平台工作线程与管理器按正确顺序启动和停止。
    """

    def __init__(
        self,
        channels_config: dict[str, Any] | None = None,
        *,
        connection_repo: Any | None = None,
        require_bound_identity: bool = False,
    ) -> None:
        """构造共享总线、映射存储、管理器及通道配置快照。"""
        self.bus = MessageBus()
        self.store = ChannelStore()
        self._connection_repo = connection_repo
        config = dict(channels_config or {})
        langgraph_url = _resolve_service_url(config, "langgraph_url", _CHANNELS_LANGGRAPH_URL_ENV, DEFAULT_LANGGRAPH_URL)
        gateway_url = _resolve_service_url(config, "gateway_url", _CHANNELS_GATEWAY_URL_ENV, DEFAULT_GATEWAY_URL)
        default_session = config.pop("session", None)
        channel_sessions = {name: channel_config.get("session") for name, channel_config in config.items() if isinstance(channel_config, dict)}
        self.manager = ChannelManager(
            bus=self.bus,
            store=self.store,
            langgraph_url=langgraph_url,
            gateway_url=gateway_url,
            default_session=default_session if isinstance(default_session, dict) else None,
            channel_sessions=channel_sessions,
            connection_repo=connection_repo,
            require_bound_identity=require_bound_identity,
        )
        self._channels: dict[str, Any] = {}  # 仅保存已成功进入运行状态的通道实例。
        self._config = config
        self._running = False
        self._readiness_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_app_config(cls, app_config: AppConfig | None = None) -> ChannelService:
        """从应用配置与运行时覆盖构造通道服务。"""
        if app_config is None:
            from deerflow.config.app_config import get_app_config

            app_config = get_app_config()
        channels_config = {}
        # ``channels`` 是 AppConfig 允许保留的扩展字段，不属于固定模型属性。
        extra = app_config.model_extra or {}
        if "channels" in extra:
            channels_config = dict(extra["channels"] or {})
        _merge_channel_connection_runtime_config(channels_config, app_config)
        connection_config = getattr(app_config, "channel_connections", None)
        connections_enabled = connection_config is not None and getattr(connection_config, "enabled", False)
        require_bound_identity = bool(connections_enabled and getattr(connection_config, "require_bound_identity", True))
        return cls(
            channels_config=channels_config,
            connection_repo=_make_connection_repo(connection_config),
            require_bound_identity=require_bound_identity,
        )

    async def start(self) -> None:
        """先启动管理器，再尝试启动全部已启用通道。"""
        if self._running:
            return

        await self.manager.start()
        self._running = True

        ready_status = await self.ensure_ready_channels(attempts=2)
        ready_count = sum(1 for ready in ready_status.values() if ready)
        logger.info("ChannelService started with %d/%d ready channels", ready_count, len(ready_status))

    async def ensure_ready_channels(self, *, attempts: int = 1) -> dict[str, bool]:
        """启动或恢复尚未就绪的已启用通道，并返回逐通道结果。"""
        ready_status: dict[str, bool] = {}
        for name, channel_config in self._config.items():
            if not isinstance(channel_config, dict):
                continue
            if not channel_config.get("enabled", False):
                if _channel_has_credentials(name, channel_config):
                    logger.warning(
                        "A configured channel has credentials configured but is disabled. Set enabled: true under its channels entry in config.yaml to activate it.",
                    )
                else:
                    logger.info("A configured channel is disabled, skipping")
                continue

            ready_status[name] = await self.ensure_channel_ready(name, attempts=attempts)
        return ready_status

    async def ensure_channel_ready(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        *,
        attempts: int = 1,
    ) -> bool:
        """使用当前有效配置确保指定通道处于运行状态。"""
        if not self._running:
            logger.warning("ChannelService is not running; cannot ensure channel readiness")
            return False

        if config is not None:
            self._config[name] = dict(config)

        # 就绪检查可能由多个请求并发触发，按通道加锁可避免同一工作线程被重复停启。
        lock = self._readiness_locks.setdefault(name, asyncio.Lock())
        async with lock:
            channel_config = self._config.get(name)
            if not channel_config or not isinstance(channel_config, dict):
                logger.warning("No config for requested channel")
                return False
            if not channel_config.get("enabled", False):
                return False

            channel = self._channels.get(name)
            if channel is not None and channel.is_running:
                return True

            if channel is not None:
                try:
                    await channel.stop()
                except Exception:
                    logger.exception("Error stopping non-running channel before readiness retry")
                self._channels.pop(name, None)

            max_attempts = max(1, attempts)
            for attempt in range(max_attempts):
                if attempt > 0:
                    logger.info("Retrying channel startup after readiness check")
                if await self._start_channel(name, channel_config):
                    return True
            return False

    async def stop(self) -> None:
        """先停止所有平台通道，再停止共享管理器。"""
        for name, channel in list(self._channels.items()):
            try:
                await channel.stop()
                logger.info("Channel stopped")
            except Exception:
                logger.exception("Error stopping channel")
        self._channels.clear()

        await self.manager.stop()
        self._running = False
        logger.info("ChannelService stopped")

    def _load_channel_config(self, name: str) -> dict[str, Any] | None:
        """从磁盘重新加载指定通道的最新有效配置。

        ``get_app_config()`` 会根据配置签名识别 ``config.yaml`` 变化；随后必须重新
        应用界面运行时覆盖，避免丢失浏览器录入凭据或重新启用已主动断开的通道。
        加载失败时回退到内存快照。
        """
        try:
            from deerflow.config.app_config import get_app_config

            app_config = get_app_config()
            extra = app_config.model_extra or {}
            channels_config = dict(extra.get("channels") or {})
            _merge_channel_connection_runtime_config(channels_config, app_config)
            channel_config = channels_config.get(name)
            if isinstance(channel_config, dict):
                # 同步内存快照，使状态查询与实际重启配置保持一致。
                self._config[name] = channel_config
                return channel_config
        except Exception:
            logger.exception("Failed to reload config for channel %s, using cached version", name)
        return self._config.get(name)

    async def restart_channel(self, name: str, *, reload_config: bool = True) -> bool:
        """停止并重新创建指定通道，成功时返回真。"""
        if name in self._channels:
            try:
                await self._channels[name].stop()
            except Exception:
                logger.exception("Error stopping channel for restart")
            del self._channels[name]

        if reload_config:
            # 读取 config.yaml 和运行时存储属于阻塞磁盘 IO，放到工作线程执行。
            config = await asyncio.to_thread(self._load_channel_config, name)
        else:
            config = self._config.get(name)
        if not config or not isinstance(config, dict):
            logger.warning("No config for requested channel")
            return False

        if not config.get("enabled", False):
            logger.info("Channel %s is disabled, skipping restart", name)
            return True

        return await self._start_channel(name, config)

    async def configure_channel(self, name: str, config: dict[str, Any]) -> bool:
        """应用权威运行时配置，并在服务运行时立即重启通道。"""
        self._config[name] = dict(config)
        if not self._running:
            return True
        # 调用方刚提供的界面配置可能从未写入 config.yaml，重启时不能再用旧磁盘值覆盖。
        return await self.restart_channel(name, reload_config=False)

    async def remove_channel(self, name: str) -> bool:
        """删除运行时配置，并停止仍在运行的对应通道。"""
        self._config.pop(name, None)
        channel = self._channels.pop(name, None)
        if channel is None:
            return True
        try:
            await channel.stop()
            logger.info("Channel stopped and removed")
            return True
        except Exception:
            logger.exception("Error stopping channel for removal")
            return False

    async def _start_channel(self, name: str, config: dict[str, Any]) -> bool:
        """惰性解析通道类，注入共享依赖并验证其成功进入运行状态。"""
        import_path = _CHANNEL_REGISTRY.get(name)
        if not import_path:
            logger.warning("Unknown channel type")
            return False

        try:
            from deerflow.reflection import resolve_class

            channel_cls = resolve_class(import_path, base_class=None)
        except Exception:
            logger.exception("Failed to import channel class")
            return False

        try:
            config = dict(config)
            config["channel_store"] = self.store
            if self._connection_repo is not None:
                config["connection_repo"] = self._connection_repo
            channel = channel_cls(bus=self.bus, config=config)
            self._channels[name] = channel
            await channel.start()
            if not channel.is_running:
                self._channels.pop(name, None)
                logger.error("Channel did not enter a running state after start()")
                return False
            logger.info("Channel started")
            return True
        except Exception:
            self._channels.pop(name, None)
            logger.exception("Failed to start channel")
            return False

    def get_status(self) -> dict[str, Any]:
        """返回服务及所有已知通道的启用与运行状态。"""
        channels_status = {}
        for name in _CHANNEL_REGISTRY:
            config = self._config.get(name, {})
            enabled = isinstance(config, dict) and config.get("enabled", False)
            running = name in self._channels and self._channels[name].is_running
            channels_status[name] = {
                "enabled": enabled,
                "running": running,
            }
        return {
            "service_running": self._running,
            "channels": channels_status,
        }

    def get_channel(self, name: str) -> Channel | None:
        """按名称返回已注册通道实例，不存在时返回 ``None``。"""
        return self._channels.get(name)

    def is_channel_enabled(self, name: str) -> bool:
        """读取实时配置中的 ``channels.<name>.enabled``。

        ``_config`` 是运行时权威快照，界面切换状态后无需重新读取 config.yaml。
        GitHub Webhook 路由以此作为分发开关；关闭通道只停止分发，不会卸载由
        ``GITHUB_WEBHOOK_SECRET`` 控制的路由。
        """
        config = self._config.get(name)
        if not isinstance(config, dict):
            return False
        return bool(config.get("enabled", False))

    def get_channel_config(self, name: str) -> dict[str, Any] | None:
        """返回实时 ``channels.<name>`` 配置的浅拷贝。

        返回 ``None`` 表示未配置，与“已配置为空或默认值”明确区分；复制可防止调用方
        意外修改管理器正在使用的权威内存状态。
        """
        config = self._config.get(name)
        if not isinstance(config, dict):
            return None
        return dict(config)


# -- 单例访问 --------------------------------------------------------------

_channel_service: ChannelService | None = None


def get_channel_service() -> ChannelService | None:
    """返回已启动的全局 ``ChannelService``，尚未创建时返回 ``None``。"""
    return _channel_service


async def start_channel_service(app_config: AppConfig | None = None) -> ChannelService:
    """从应用配置创建并启动全局 ``ChannelService``。"""
    global _channel_service
    if _channel_service is not None:
        return _channel_service
    # from_app_config 会读取 JSON 映射和运行时配置文件，必须避开事件循环。
    _channel_service = await asyncio.to_thread(ChannelService.from_app_config, app_config)
    await _channel_service.start()
    return _channel_service


async def stop_channel_service() -> None:
    """停止并清除全局 ``ChannelService``。"""
    global _channel_service
    if _channel_service is not None:
        await _channel_service.stop()
        _channel_service = None
