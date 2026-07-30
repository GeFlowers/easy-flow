"""提供配置、checkpointer、配置相关功能。"""

from typing import Literal

from pydantic import BaseModel, Field

CheckpointerType = Literal["memory", "sqlite", "postgres"]


class CheckpointerConfig(BaseModel):
    """\u6267\u884c CheckpointerConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    type: CheckpointerType = Field(
        description="Checkpointer backend type. "
        "'memory' is in-process only (lost on restart). "
        "'sqlite' persists to a local file (requires langgraph-checkpoint-sqlite). "
        "'postgres' persists to PostgreSQL (install with deerflow-harness[postgres])."
    )
    connection_string: str | None = Field(
        default=None,
        description="Connection string for sqlite (file path) or postgres (DSN). "
        "Optional for sqlite and defaults to 'store.db' when omitted. "
        "Required for postgres. "
        "For sqlite, use a file path like '.deer-flow/checkpoints.db' or ':memory:' for in-memory. "
        "For postgres, use a DSN like 'postgresql://user:pass@localhost:5432/db'.",
    )


# 中文说明：此处用于执行相关处理。
_checkpointer_config: CheckpointerConfig | None = None


def get_checkpointer_config() -> CheckpointerConfig | None:
    """\u6267\u884c get_checkpointer_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return _checkpointer_config


def set_checkpointer_config(config: CheckpointerConfig | None) -> None:
    """\u6267\u884c set_checkpointer_config \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _checkpointer_config
    _checkpointer_config = config


def ensure_config_loaded() -> None:
    """\u6267\u884c ensure_config_loaded \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    from deerflow.config.app_config import _app_config, get_app_config

    config = get_checkpointer_config()
    if config is not None or _app_config is not None:
        return

    try:
        get_app_config()
    except FileNotFoundError:
        pass


def load_checkpointer_config_from_dict(config_dict: dict | None) -> None:
    """\u6267\u884c load_checkpointer_config_from_dict \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _checkpointer_config
    if config_dict is None:
        _checkpointer_config = None
        return
    _checkpointer_config = CheckpointerConfig(**config_dict)
