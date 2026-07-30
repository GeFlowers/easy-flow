"定义 paths 模块提供的职责与可复用接口。\n\nDeerMem's own storage path resolution (no deer-flow ``get_paths`` / ``AGENT_NAME_PATTERN``).\n\nThe host no longer dictates where DeerMem stores data. Root = ``config.storage_path``\n(if set, absolute or relative) or ``$DEERMEM_DATA_DIR`` or ``~/.deermem/``.\nPer-user / per-agent / legacy layouts live under the root, mirroring the\npre-abstraction paths so a one-time data migration (old ``{base_dir}/users/*``\n-> DeerMem root) is a plain move.\n\nuser_id is sanitized in-process (``[A-Za-z0-9_-]`` + SHA-256 digest for lossy\nids) and agent_name validated against an inlined pattern -- DeerMem does not\nimport the host's ``make_safe_user_id`` / ``_validate_user_id`` /\n``AGENT_NAME_PATTERN``.\n"

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import DeerMemConfig

# user_id charset + sanitization (mirrors the host's make_safe_user_id so
# existing per-user buckets line up after migration).
_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_UNSAFE_USER_ID_CHAR_RE = re.compile(r"[^A-Za-z0-9_\-]")
_SAFE_USER_ID_DIGEST_HEX_LEN = 16

# agent_name validation (inlined; was deer-flow's AGENT_NAME_PATTERN).
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def safe_user_id(raw: str) -> str:
    "执行 safe_user_id 的明确职责，并返回与调用约定一致的结果。\n\nNormalize an external identity into the user-id charset (``[A-Za-z0-9_-]``).\n\n    Idempotent: already-safe ids pass through; lossy ones get a short SHA-256\n    digest suffix so two distinct inputs never share a bucket. Mirrors the\n    host's ``make_safe_user_id`` so existing per-user buckets line up after\n    migration.\n    "
    if not raw:
        raise ValueError("user_id must be a non-empty string.")
    sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw)
    if sanitized == raw:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def validate_agent_name(name: str) -> None:
    '校验输入并在约束不满足时报告错误，并遵守 validate_agent_name 所表达的接口约束。\n\nValidate that the agent name is safe to use in filesystem paths.'
    if not name:
        raise ValueError("Agent name must be a non-empty string.")
    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid agent name {name!r}: names must match {AGENT_NAME_PATTERN.pattern}")


def _default_root() -> Path:
    "执行 _default_root 的明确职责，并返回与调用约定一致的结果。\n\nDeerMem's default data root: ``$DEERMEM_DATA_DIR`` or ``~/.deermem/``."
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
    "执行 memory_file_path 的明确职责，并返回与调用约定一致的结果。\n\nResolve the memory file path under DeerMem's own data root.\n\n    ``config.storage_path`` (absolute or relative) is the root; per-user /\n    per-agent / legacy layouts live under it. Empty -> default root\n    (``$DEERMEM_DATA_DIR`` / ``~/.deermem/``). The host (deer-flow factory)\n    injects an absolute base_dir as ``storage_path`` so memory lands at\n    ``{base_dir}/users/{user_id}/memory.json`` (CWD-independent).\n    "
    root = Path(config.storage_path) if config.storage_path else _default_root()

    if user_id is not None:
        uid = safe_user_id(user_id)
        if agent_name is not None:
            validate_agent_name(agent_name)
            return root / "users" / uid / "agents" / agent_name.lower() / "memory.json"
        return root / "users" / uid / "memory.json"
    # Legacy: no user_id
    if agent_name is not None:
        validate_agent_name(agent_name)
        return root / "agents" / agent_name.lower() / "memory.json"
    return root / "memory.json"
