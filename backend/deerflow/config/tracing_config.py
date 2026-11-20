'''从环境变量构造 Langfuse 追踪配置并校验凭据。'''

import os
import threading

from pydantic import BaseModel, Field

_config_lock = threading.Lock()


class LangfuseTracingConfig(BaseModel):
    '''保存 Langfuse 追踪端点以及公钥、密钥和启用状态。'''

    enabled: bool = Field(...)
    public_key: str | None = Field(...)
    secret_key: str | None = Field(...)
    host: str = Field(...)

    @property
    def is_configured(self) -> bool:
        '''检查追踪开关和成对凭据是否齐备。'''
        return self.enabled and bool(self.public_key) and bool(self.secret_key)

    def validate(self) -> None:
        '''列出缺失的 Langfuse 凭据，并在启用配置不完整时报错。'''
        if not self.enabled:
            return
        missing: list[str] = []
        if not self.public_key:
            missing.append("LANGFUSE_PUBLIC_KEY")
        if not self.secret_key:
            missing.append("LANGFUSE_SECRET_KEY")
        if missing:
            raise ValueError(f"Langfuse tracing is enabled but required settings are missing: {', '.join(missing)}")


class TracingConfig(BaseModel):
    '''汇总追踪设置，并提供统一的可用性判定。'''

    langfuse: LangfuseTracingConfig = Field(...)

    @property
    def is_configured(self) -> bool:
        '''根据已具备凭据的 Langfuse 配置判断回调式追踪是否可用。'''
        return bool(self.enabled_providers)

    @property
    def explicitly_enabled_providers(self) -> list[str]:
        '''列出用户显式打开的追踪服务，即使其凭据尚未配置。'''
        enabled: list[str] = []
        if self.langfuse.enabled:
            enabled.append("langfuse")
        return enabled

    @property
    def enabled_providers(self) -> list[str]:
        '''只列出已启用且凭据齐全、能够实际创建回调的服务。'''
        enabled: list[str] = []
        if self.langfuse.is_configured:
            enabled.append("langfuse")
        return enabled

    def validate_enabled(self) -> None:
        '''校验已开启的 Langfuse 配置是否具备必需凭据。'''
        self.langfuse.validate()


_tracing_config: TracingConfig | None = None


_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def get_tracing_config() -> TracingConfig:
    '''线程安全地从环境变量构造并缓存所有追踪供应商配置。'''
    global _tracing_config
    if _tracing_config is not None:
        return _tracing_config
    with _config_lock:
        if _tracing_config is not None:
            return _tracing_config
        _tracing_config = TracingConfig(
            langfuse=LangfuseTracingConfig(
                enabled=_env_flag_preferred("LANGFUSE_TRACING"),
                public_key=_first_env_value("LANGFUSE_PUBLIC_KEY"),
                secret_key=_first_env_value("LANGFUSE_SECRET_KEY"),
                host=_first_env_value("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com",
            ),
        )
        return _tracing_config


def _env_flag_preferred(*names: str) -> bool:
    '''按变量优先级读取布尔开关，第一个非空值决定最终结果。'''
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip().lower() in _TRUTHY_VALUES
    return False


def _first_env_value(*names: str) -> str | None:
    '''按给定优先级返回第一个非空环境变量值。'''
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def get_enabled_tracing_providers() -> list[str]:
    '''返回当前凭据完整且可创建回调的追踪供应商名称。'''
    return get_tracing_config().enabled_providers


def get_explicitly_enabled_tracing_providers() -> list[str]:
    '''返回环境配置中被显式打开的追踪供应商名称。'''
    return get_tracing_config().explicitly_enabled_providers


def validate_enabled_tracing_providers() -> None:
    '''在应用启动时校验所有显式启用且需要凭据的追踪服务。'''
    get_tracing_config().validate_enabled()


def is_tracing_enabled() -> bool:
    '''判断是否至少有一个已配置的回调式追踪供应商。'''
    return get_tracing_config().is_configured


def reset_tracing_config() -> None:
    '''清空追踪配置缓存，使后续读取重新采集环境变量。'''
    global _tracing_config
    with _config_lock:
        _tracing_config = None
