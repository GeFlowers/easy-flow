'''持久化由界面在运行时写入的即时通讯通道配置。'''

from __future__ import annotations

import json
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RUNTIME_CHANNEL_DISABLED_FLAG = "_runtime_disabled"


class ChannelRuntimeConfigStore:
    '''以本地 JSON 文件保存界面录入的通道凭据与启停状态。

    该存储刻意保持与 ``ChannelStore`` 相同的轻量方案，使本地或私有部署无需公开
    回调地址，也无需直接编辑 ``config.yaml``，即可跨进程重启保留通道配置。
    '''

    def __init__(self, path: str | Path | None = None) -> None:
        '''解析存储路径并在内存中加载当前配置快照。'''
        if path is None:
            from deerflow.config.paths import get_paths

            path = Path(get_paths().base_dir) / "channels" / "runtime-config.json"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = self._load()
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, Any]]:
        '''读取有效的提供商配置，并在文件损坏时安全退化为空配置。'''
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt channel runtime config store at %s, starting fresh", self._path)
                return {}
            if isinstance(raw, dict):
                return {str(name): dict(value) for name, value in raw.items() if isinstance(value, dict)}
        return {}

    def _save(self) -> None:
        '''通过同目录临时文件原子替换配置，并尽量收紧凭据文件权限。'''
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            # 临时文件与最终文件都设为仅所有者可读写，避免凭据在替换窗口中暴露。
            try:
                Path(fd.name).chmod(0o600)
            except OSError:
                logger.debug("Unable to chmod temporary channel runtime config store at %s", fd.name, exc_info=True)
            json.dump(self._data, fd, indent=2, ensure_ascii=False)
            fd.close()
            Path(fd.name).replace(self._path)
            try:
                self._path.chmod(0o600)
            except OSError:
                logger.debug("Unable to chmod channel runtime config store at %s", self._path, exc_info=True)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    def load_all(self) -> dict[str, dict[str, Any]]:
        '''返回全部配置的浅拷贝，防止调用方绕过锁修改内部状态。'''
        with self._lock:
            return {name: dict(config) for name, config in self._data.items()}

    def get_provider_config(self, provider: str) -> dict[str, Any] | None:
        '''返回单个提供商配置的副本，不存在时返回 ``None``。'''
        with self._lock:
            config = self._data.get(provider)
            return dict(config) if isinstance(config, dict) else None

    def set_provider_config(self, provider: str, config: dict[str, Any]) -> None:
        '''替换提供商配置并在同一临界区内持久化。'''
        with self._lock:
            self._data[provider] = dict(config)
            self._save()

    def set_provider_disconnected(self, provider: str) -> None:
        '''记录用户主动断开状态，使静态配置也不会在重启后重新启用通道。'''
        with self._lock:
            self._data[provider] = {
                "enabled": False,
                RUNTIME_CHANNEL_DISABLED_FLAG: True,
            }
            self._save()

    def remove_provider_config(self, provider: str) -> bool:
        '''删除提供商覆盖配置，并返回是否实际发生删除。'''
        with self._lock:
            if provider not in self._data:
                return False
            del self._data[provider]
            self._save()
            return True


def _provider_enabled(channel_connections_config: Any, provider: str) -> bool:
    '''判断全局连接配置是否允许对应提供商使用运行时覆盖。'''
    provider_config = getattr(channel_connections_config, provider, None)
    return bool(getattr(provider_config, "enabled", False))


def _runtime_channel_disconnected(runtime_config: dict[str, Any]) -> bool:
    '''识别用户显式断开而非普通的暂时禁用配置。'''
    return runtime_config.get(RUNTIME_CHANNEL_DISABLED_FLAG) is True and runtime_config.get("enabled") is False


def merge_runtime_channel_configs(
    channels_config: dict[str, Any],
    channel_connections_config: Any,
    *,
    store: ChannelRuntimeConfigStore | None = None,
) -> None:
    '''把允许的运行时提供商配置原地合并到 ``channels_config``。

    运行时值拥有更高优先级，但仅对全局连接配置明确启用的提供商生效；显式断开
    标记会删除静态通道项，避免重启后意外恢复连接。
    '''
    if channel_connections_config is None or not getattr(channel_connections_config, "enabled", False):
        return

    runtime_store = store or ChannelRuntimeConfigStore()
    for provider, runtime_config in runtime_store.load_all().items():
        if not _provider_enabled(channel_connections_config, provider):
            continue
        if _runtime_channel_disconnected(runtime_config):
            channels_config.pop(provider, None)
            continue
        existing = channels_config.get(provider)
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(runtime_config)
        channels_config[provider] = merged


def apply_runtime_connection_config(
    channel_connections_config: Any,
    *,
    store: ChannelRuntimeConfigStore | None = None,
) -> Any:
    '''应用不属于 ``channels`` 主配置树的持久化连接元数据。

    Telegram 深链需要机器人用户名。该值与运行时通道配置一起保存，并通过模型
    深拷贝注入，避免修改由配置系统共享的原对象。
    '''
    if channel_connections_config is None or not getattr(channel_connections_config, "enabled", False):
        return channel_connections_config

    return channel_connections_config
