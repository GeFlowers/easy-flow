"""提供配置、paths相关功能。"""

import hashlib
import logging
import os
import re
import shutil
from pathlib import Path, PureWindowsPath

from deerflow.config.runtime_paths import runtime_home

# 中文说明：此处用于执行相关处理。
VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_UNSAFE_USER_ID_CHAR_RE = re.compile(r"[^A-Za-z0-9_\-]")
_SAFE_USER_ID_DIGEST_HEX_LEN = 16

logger = logging.getLogger(__name__)


def _default_local_base_dir() -> Path:
    """\u6267\u884c _default_local_base_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return runtime_home()


def _validate_thread_id(thread_id: str) -> str:
    """\u6267\u884c _validate_thread_id \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    if not _SAFE_THREAD_ID_RE.match(thread_id):
        raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return thread_id


def _validate_user_id(user_id: str) -> str:
    """\u6267\u884c _validate_user_id \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    if not _SAFE_USER_ID_RE.match(user_id):
        raise ValueError(f"Invalid user_id {user_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return user_id


def make_safe_user_id(raw: str) -> str:
    """\u6267\u884c make_safe_user_id \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    if not raw:
        raise ValueError("user_id must be a non-empty string.")
    sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw)
    if sanitized == raw:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def _legacy_safe_user_id(raw: str, sanitized: str) -> str:
    """\u6267\u884c _legacy_safe_user_id \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def _join_host_path(base: str, *parts: str) -> str:
    """\u6267\u884c _join_host_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    if not parts:
        return base

    if re.match(r"^[A-Za-z]:[\\/]", base) or base.startswith("\\\\") or "\\" in base:
        result = PureWindowsPath(base)
        for part in parts:
            result /= part
        return str(result)

    result = Path(base)
    for part in parts:
        result /= part
    return str(result)


def join_host_path(base: str, *parts: str) -> str:
    """\u6267\u884c join_host_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    return _join_host_path(base, *parts)


class Paths:
    """\u6267\u884c Paths \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        """\u6267\u884c __init__ \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def host_base_dir(self) -> Path:
        """\u6267\u884c host_base_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return Path(env)
        return self.base_dir

    def _host_base_dir_str(self) -> str:
        """\u6267\u884c _host_base_dir_str \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return env
        return str(self.base_dir)

    @property
    def base_dir(self) -> Path:
        """\u6267\u884c base_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        return _default_local_base_dir()

    @property
    def memory_file(self) -> Path:
        """\u6267\u884c memory_file \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        """\u6267\u884c user_md_file \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.base_dir / "USER.md"

    @property
    def agents_dir(self) -> Path:
        """\u6267\u884c agents_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.base_dir / "agents"

    def agent_dir(self, name: str) -> Path:
        """\u6267\u884c agent_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        """\u6267\u884c agent_memory_file \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.agent_dir(name) / "memory.json"

    def user_dir(self, user_id: str) -> Path:
        """\u6267\u884c user_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.base_dir / "users" / _validate_user_id(user_id)

    def prepare_user_dir_for_raw_id(self, raw_user_id: str) -> str:
        """\u6267\u884c prepare_user_dir_for_raw_id \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        safe_user_id = make_safe_user_id(raw_user_id)
        sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw_user_id)
        if safe_user_id == raw_user_id:
            return safe_user_id

        users_dir = self.base_dir / "users"
        target_dir = users_dir / safe_user_id
        legacy_dir = users_dir / _legacy_safe_user_id(raw_user_id, sanitized)
        try:
            if target_dir.exists() or not legacy_dir.is_dir():
                return safe_user_id
            legacy_dir.rename(target_dir)
            logger.info("Migrated legacy unsafe-id user directory to the current digest format")
        except OSError:
            logger.exception("Failed to migrate legacy unsafe-id user directory")
        return safe_user_id

    def user_memory_file(self, user_id: str) -> Path:
        """\u6267\u884c user_memory_file \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.user_dir(user_id) / "memory.json"

    def user_agents_dir(self, user_id: str) -> Path:
        """\u6267\u884c user_agents_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.user_dir(user_id) / "agents"

    def user_agent_dir(self, user_id: str, agent_name: str) -> Path:
        """\u6267\u884c user_agent_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.user_agents_dir(user_id) / agent_name.lower()

    def user_agent_memory_file(self, user_id: str, agent_name: str) -> Path:
        """\u6267\u884c user_agent_memory_file \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.user_agent_dir(user_id, agent_name) / "memory.json"

    def user_skills_dir(self, user_id: str) -> Path:
        """\u6267\u884c user_skills_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.user_dir(user_id) / "skills"

    def user_custom_skills_dir(self, user_id: str) -> Path:
        """\u6267\u884c user_custom_skills_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.user_skills_dir(user_id) / "custom"

    def thread_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """\u6267\u884c thread_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if user_id is not None:
            return self.user_dir(user_id) / "threads" / _validate_thread_id(thread_id)
        return self.base_dir / "threads" / _validate_thread_id(thread_id)

    def sandbox_work_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """\u6267\u884c sandbox_work_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "workspace"

    def sandbox_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """\u6267\u884c sandbox_uploads_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "uploads"

    def sandbox_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """\u6267\u884c sandbox_outputs_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "outputs"

    def acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """\u6267\u884c acp_workspace_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.thread_dir(thread_id, user_id=user_id) / "acp-workspace"

    def sandbox_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """\u6267\u884c sandbox_user_data_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return self.thread_dir(thread_id, user_id=user_id) / "user-data"

    def host_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """\u6267\u884c host_thread_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if user_id is not None:
            return _join_host_path(self._host_base_dir_str(), "users", _validate_user_id(user_id), "threads", _validate_thread_id(thread_id))
        return _join_host_path(self._host_base_dir_str(), "threads", _validate_thread_id(thread_id))

    def host_sandbox_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """\u6267\u884c host_sandbox_user_data_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return _join_host_path(self.host_thread_dir(thread_id, user_id=user_id), "user-data")

    def host_sandbox_work_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """\u6267\u884c host_sandbox_work_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "workspace")

    def host_sandbox_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """\u6267\u884c host_sandbox_uploads_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "uploads")

    def host_sandbox_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """\u6267\u884c host_sandbox_outputs_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "outputs")

    def host_acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """\u6267\u884c host_acp_workspace_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return _join_host_path(self.host_thread_dir(thread_id, user_id=user_id), "acp-workspace")

    def ensure_thread_dirs(self, thread_id: str, *, user_id: str | None = None) -> None:
        """\u6267\u884c ensure_thread_dirs \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        for d in [
            self.sandbox_work_dir(thread_id, user_id=user_id),
            self.sandbox_uploads_dir(thread_id, user_id=user_id),
            self.sandbox_outputs_dir(thread_id, user_id=user_id),
            self.acp_workspace_dir(thread_id, user_id=user_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o777)

    def delete_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> None:
        """\u6267\u884c delete_thread_dir \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        thread_dir = self.thread_dir(thread_id, user_id=user_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    def resolve_virtual_path(self, thread_id: str, virtual_path: str, *, user_id: str | None = None) -> Path:
        """\u6267\u884c resolve_virtual_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

        # 中文说明：此处用于执行相关处理。
        # 中文说明：此处用于执行相关处理。
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.sandbox_user_data_dir(thread_id, user_id=user_id).resolve()
        actual = (base / relative).resolve()

        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected")

        return actual


# 中文说明：此处用于执行相关处理。

_paths: Paths | None = None


def get_paths() -> Paths:
    """\u6267\u884c get_paths \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    """\u6267\u884c resolve_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()
