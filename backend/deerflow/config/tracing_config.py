'''从环境变量构造 LangSmith、Langfuse 和 Monocle 的追踪配置并校验凭据。'''

import os
import threading

from pydantic import BaseModel, Field

_config_lock = threading.Lock()


class LangSmithTracingConfig(BaseModel):
    '''保存 LangSmith 追踪开关、密钥、项目名和服务端点。'''

    enabled: bool = Field(...)
    api_key: str | None = Field(...)
    project: str = Field(...)
    endpoint: str = Field(...)

    @property
    def is_configured(self) -> bool:
        '''只有启用追踪且存在 API 密钥时才视为可连接。'''
        return self.enabled and bool(self.api_key)

    def validate(self) -> None:
        '''在启用但缺少密钥时中止配置装载，避免静默丢失追踪数据。'''
        if self.enabled and not self.api_key:
            raise ValueError("LangSmith tracing is enabled but LANGSMITH_API_KEY (or LANGCHAIN_API_KEY) is not set.")


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
_MONOCLE_EXPORTERS = ("file", "console", "okahu", "s3", "blob", "gcs")


class MonocleTracingConfig(BaseModel):
    '''配置 Monocle 追踪开关、导出器列表及 Okahu 凭据。'''

    enabled: bool = Field(...)
    exporters: str = Field(...)
    okahu_api_key: str | None = Field(...)

    @property
    def is_enabled(self) -> bool:
        '''返回 Monocle 导出是否启用；该集成无需每次运行创建回调。'''
        return self.enabled

    @property
    def exporter_list(self) -> list[str]:
        '''将逗号分隔的导出器配置解析为去除空白的名称列表。'''
        return [e.strip() for e in self.exporters.split(",") if e.strip()]

    def validate(self) -> None:
        '''拒绝未知导出器，并检查 Okahu 导出器所需密钥。'''
        if not self.enabled:
            return
        selected = self.exporter_list
        unknown = [e for e in selected if e not in _MONOCLE_EXPORTERS]
        if unknown:
            raise ValueError(f"MONOCLE_EXPORTERS has unknown exporter(s): {', '.join(unknown)}. Allowed: {', '.join(_MONOCLE_EXPORTERS)}.")
        if "okahu" in selected and not self.okahu_api_key:
            raise ValueError("Monocle 'okahu' exporter is selected but OKAHU_API_KEY is not set.")


class TracingConfig(BaseModel):
    '''汇总多个追踪供应商设置，并提供统一的可用性判定。'''

    langsmith: LangSmithTracingConfig = Field(...)
    langfuse: LangfuseTracingConfig = Field(...)
    monocle: MonocleTracingConfig = Field(...)

    @property
    def is_configured(self) -> bool:
        '''根据已具备凭据的 LangSmith 或 Langfuse 配置判断追踪是否可用。'''
        return bool(self.enabled_providers)

    @property
    def explicitly_enabled_providers(self) -> list[str]:
        '''列出用户显式打开的追踪服务，即使其凭据尚未配置。'''
        enabled: list[str] = []
        if self.langsmith.enabled:
            enabled.append("langsmith")
        if self.langfuse.enabled:
            enabled.append("langfuse")
        return enabled

    @property
    def enabled_providers(self) -> list[str]:
        '''只列出已启用且凭据齐全、能够实际创建回调的服务。'''
        enabled: list[str] = []
        if self.langsmith.is_configured:
            enabled.append("langsmith")
        if self.langfuse.is_configured:
            enabled.append("langfuse")
        return enabled

    def validate_enabled(self) -> None:
        '''校验已开启的 LangSmith 和 Langfuse 配置是否具备必需凭据。'''
        self.langsmith.validate()
        self.langfuse.validate()


_tracing_config: TracingConfig | None = None


_TRUTHY_VALUES = {"1", "true", "yes", "on"}


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


def get_tracing_config() -> TracingConfig:
    '''线程安全地从环境变量构造并缓存所有追踪供应商配置。'''
    global _tracing_config
    if _tracing_config is not None:
        return _tracing_config
    with _config_lock:
        if _tracing_config is not None:
            return _tracing_config
        _tracing_config = TracingConfig(
            langsmith=LangSmithTracingConfig(
                enabled=_env_flag_preferred("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"),
                api_key=_first_env_value("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
                project=_first_env_value("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT") or "deer-flow",
                endpoint=_first_env_value("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT") or "https://api.smith.langchain.com",
            ),
            langfuse=LangfuseTracingConfig(
                enabled=_env_flag_preferred("LANGFUSE_TRACING"),
                public_key=_first_env_value("LANGFUSE_PUBLIC_KEY"),
                secret_key=_first_env_value("LANGFUSE_SECRET_KEY"),
                host=_first_env_value("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com",
            ),
            monocle=MonocleTracingConfig(
                enabled=_env_flag_preferred("MONOCLE_TRACING"),
                exporters=_first_env_value("MONOCLE_EXPORTERS") or "file",
                okahu_api_key=_first_env_value("OKAHU_API_KEY"),
            ),
        )
        return _tracing_config


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


def is_monocle_tracing_enabled() -> bool:
    '''判断是否开启 Monocle 进程级追踪导出。'''
    return get_tracing_config().monocle.is_enabled


def reset_tracing_config() -> None:
    '''清空追踪配置缓存，使后续读取重新采集环境变量。'''
    global _tracing_config
    with _config_lock:
        _tracing_config = None
