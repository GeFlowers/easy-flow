"""提供配置、runtime、paths相关功能。"""

import os
from pathlib import Path


def project_root() -> Path:
    """\u6267\u884c project_root \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    if env_root := os.getenv("DEER_FLOW_PROJECT_ROOT"):
        root = Path(env_root).resolve()
        if not root.exists():
            raise ValueError(f"DEER_FLOW_PROJECT_ROOT is set to '{env_root}', but the resolved path '{root}' does not exist.")
        if not root.is_dir():
            raise ValueError(f"DEER_FLOW_PROJECT_ROOT is set to '{env_root}', but the resolved path '{root}' is not a directory.")
        return root
    return Path.cwd().resolve()


def runtime_home() -> Path:
    """\u6267\u884c runtime_home \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    if env_home := os.getenv("DEER_FLOW_HOME"):
        return Path(env_home).resolve()
    return project_root() / ".deer-flow"


def resolve_path(value: str | os.PathLike[str], *, base: Path | None = None) -> Path:
    """\u6267\u884c resolve_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    path = Path(value)
    if not path.is_absolute():
        path = (base or project_root()) / path
    return path.resolve()


def existing_project_file(names: tuple[str, ...]) -> Path | None:
    """\u6267\u884c existing_project_file \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    root = project_root()
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None
