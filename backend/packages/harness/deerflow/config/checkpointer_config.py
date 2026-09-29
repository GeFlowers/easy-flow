"""提供配置、checkpointer、配置相关功能。"""

from typing import Literal

from pydantic import BaseModel, Field

CheckpointerType = Literal["postgres"]


class CheckpointerConfig(BaseModel):
    """\u6267\u884c CheckpointerConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    type: CheckpointerType = Field(
        description="PostgreSQL checkpointer backend (install with deerflow-harness[postgres])."
    )
    connection_string: str | None = Field(
        default=None,
        description="PostgreSQL DSN, for example 'postgresql://user:pass@localhost:5432/db'.",
    )
_checkpointer_config: CheckpointerConfig | None = None


def get_checkpointer_config() -> CheckpointerConfig | None:
    """返回当前缓存的检查点配置；尚未加载配置时返回 None。"""
    return _checkpointer_config


def set_checkpointer_config(config: CheckpointerConfig | None) -> None:
    """替换进程内缓存的检查点配置。"""
    global _checkpointer_config
    _checkpointer_config = config


def ensure_config_loaded() -> None:
    """在检查点配置尚未初始化时触发应用配置加载。"""
    from deerflow.config.app_config import _app_config, get_app_config

    config = get_checkpointer_config()
    if config is not None or _app_config is not None:
        return

    try:
        get_app_config()
    except FileNotFoundError:
        pass


def load_checkpointer_config_from_dict(config_dict: dict | None) -> None:
    """从配置字典创建检查点配置；传入 None 时清空缓存。"""
    global _checkpointer_config
    if config_dict is None:
        _checkpointer_config = None
        return
    _checkpointer_config = CheckpointerConfig(**config_dict)
