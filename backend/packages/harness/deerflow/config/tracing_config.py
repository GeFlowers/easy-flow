"""提供配置、追踪、配置相关功能。"""

import os
import threading

from pydantic import BaseModel, Field

_config_lock = threading.Lock()


class LangSmithTracingConfig(BaseModel):
    """\u6267\u884c LangSmithTracingConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(...)
    api_key: str | None = Field(...)
    project: str = Field(...)
    endpoint: str = Field(...)

    @property
    def is_configured(self) -> bool:
        """\u6267\u884c is_configured \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.enabled and bool(self.api_key)

    def validate(self) -> None:
        """\u6267\u884c validate \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if self.enabled and not self.api_key:
            raise ValueError("LangSmith tracing is enabled but LANGSMITH_API_KEY (or LANGCHAIN_API_KEY) is not set.")


class LangfuseTracingConfig(BaseModel):
    """\u6267\u884c LangfuseTracingConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(...)
    public_key: str | None = Field(...)
    secret_key: str | None = Field(...)
    host: str = Field(...)

    @property
    def is_configured(self) -> bool:
        """\u6267\u884c is_configured \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.enabled and bool(self.public_key) and bool(self.secret_key)

    def validate(self) -> None:
        """\u6267\u884c validate \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if not self.enabled:
            return
        missing: list[str] = []
        if not self.public_key:
            missing.append("LANGFUSE_PUBLIC_KEY")
        if not self.secret_key:
            missing.append("LANGFUSE_SECRET_KEY")
        if missing:
            raise ValueError(f"Langfuse tracing is enabled but required settings are missing: {', '.join(missing)}")


# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
# 中文说明：此处用于执行相关处理。
_MONOCLE_EXPORTERS = ("file", "console", "okahu", "s3", "blob", "gcs")


class MonocleTracingConfig(BaseModel):
    """\u6267\u884c MonocleTracingConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    enabled: bool = Field(...)
    exporters: str = Field(...)
    okahu_api_key: str | None = Field(...)

    @property
    def is_enabled(self) -> bool:
        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        """\u6267\u884c is_enabled \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.enabled

    @property
    def exporter_list(self) -> list[str]:
        """\u6267\u884c exporter_list \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return [e.strip() for e in self.exporters.split(",") if e.strip()]

    def validate(self) -> None:
        """\u6267\u884c validate \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if not self.enabled:
            return
        selected = self.exporter_list
        unknown = [e for e in selected if e not in _MONOCLE_EXPORTERS]
        if unknown:
            raise ValueError(f"MONOCLE_EXPORTERS has unknown exporter(s): {', '.join(unknown)}. Allowed: {', '.join(_MONOCLE_EXPORTERS)}.")
        if "okahu" in selected and not self.okahu_api_key:
            raise ValueError("Monocle 'okahu' exporter is selected but OKAHU_API_KEY is not set.")


class TracingConfig(BaseModel):
    """\u6267\u884c TracingConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    langsmith: LangSmithTracingConfig = Field(...)
    langfuse: LangfuseTracingConfig = Field(...)
    monocle: MonocleTracingConfig = Field(...)

    @property
    def is_configured(self) -> bool:
        """\u6267\u884c is_configured \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return bool(self.enabled_providers)

    @property
    def explicitly_enabled_providers(self) -> list[str]:
        """\u6267\u884c explicitly_enabled_providers \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        enabled: list[str] = []
        if self.langsmith.enabled:
            enabled.append("langsmith")
        if self.langfuse.enabled:
            enabled.append("langfuse")
        return enabled

    @property
    def enabled_providers(self) -> list[str]:
        """\u6267\u884c enabled_providers \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        enabled: list[str] = []
        if self.langsmith.is_configured:
            enabled.append("langsmith")
        if self.langfuse.is_configured:
            enabled.append("langfuse")
        return enabled

    def validate_enabled(self) -> None:
        """\u6267\u884c validate_enabled \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        self.langsmith.validate()
        self.langfuse.validate()


_tracing_config: TracingConfig | None = None


_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _env_flag_preferred(*names: str) -> bool:
    """\u6267\u884c _env_flag_preferred \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip().lower() in _TRUTHY_VALUES
    return False


def _first_env_value(*names: str) -> str | None:
    """\u6267\u884c _first_env_value \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def get_tracing_config() -> TracingConfig:
    """\u6267\u884c get_tracing_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
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
    """\u6267\u884c get_enabled_tracing_providers \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return get_tracing_config().enabled_providers


def get_explicitly_enabled_tracing_providers() -> list[str]:
    """\u6267\u884c get_explicitly_enabled_tracing_providers \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return get_tracing_config().explicitly_enabled_providers


def validate_enabled_tracing_providers() -> None:
    """\u6267\u884c validate_enabled_tracing_providers \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    get_tracing_config().validate_enabled()


def is_tracing_enabled() -> bool:
    """\u6267\u884c is_tracing_enabled \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return get_tracing_config().is_configured


def is_monocle_tracing_enabled() -> bool:
    """\u6267\u884c is_monocle_tracing_enabled \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return get_tracing_config().monocle.is_enabled


def reset_tracing_config() -> None:
    """\u6267\u884c reset_tracing_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _tracing_config
    with _config_lock:
        _tracing_config = None
