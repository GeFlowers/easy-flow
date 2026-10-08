'''解析记忆文件根目录，并安全构造按用户及代理隔离的文件路径。'''

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import DeerMemConfig

_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_UNSAFE_USER_ID_CHAR_RE = re.compile(r"[^A-Za-z0-9_\-]")
_SAFE_USER_ID_DIGEST_HEX_LEN = 16

AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def safe_user_id(raw: str) -> str:
    '''将外部用户标识转换为安全路径片段；发生字符替换时追加摘要以避免标识冲突。'''
    if not raw:
        raise ValueError("user_id must be a non-empty string.")
    sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw)
    if sanitized == raw:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def validate_agent_name(name: str) -> None:
    '''确保代理名称非空且只含路径允许的字符，防止名称改变目标目录结构。'''
    if not name:
        raise ValueError("Agent name must be a non-empty string.")
    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid agent name {name!r}: names must match {AGENT_NAME_PATTERN.pattern}")


def _default_root() -> Path:
    '''返回环境变量指定的数据目录；未配置时使用用户主目录下的 .deermem。'''
    env = os.environ.get("DEERMEM_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".deermem"


def memory_file_path(
    config: DeerMemConfig,
    agent_name: str | None = None,
    *,
    user_id: str | None = None,
) -> Path:
    '''按配置根目录、用户标识和代理名称解析记忆文件位置，同时兼容未指定用户的旧目录布局。'''
    root = Path(config.storage_path) if config.storage_path else _default_root()

    if user_id is not None:
        uid = safe_user_id(user_id)
        if agent_name is not None:
            validate_agent_name(agent_name)
            return root / "users" / uid / "agents" / agent_name.lower() / "memory.json"
        return root / "users" / uid / "memory.json"
    if agent_name is not None:
        validate_agent_name(agent_name)
        return root / "agents" / agent_name.lower() / "memory.json"
    return root / "memory.json"
