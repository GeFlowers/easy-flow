'''解析项目根目录、运行数据根目录以及相对配置文件路径。'''

import os
from pathlib import Path


def project_root() -> Path:
    '''读取项目根目录环境变量；未设置时以当前工作目录作为项目根。'''
    if env_root := os.getenv("DEER_FLOW_PROJECT_ROOT"):
        root = Path(env_root).resolve()
        if not root.exists():
            raise ValueError(f"DEER_FLOW_PROJECT_ROOT is set to '{env_root}', but the resolved path '{root}' does not exist.")
        if not root.is_dir():
            raise ValueError(f"DEER_FLOW_PROJECT_ROOT is set to '{env_root}', but the resolved path '{root}' is not a directory.")
        return root
    return Path.cwd().resolve()


def runtime_home() -> Path:
    '''返回运行数据目录，默认放在项目根下的 ``.deer-flow``。'''
    if env_home := os.getenv("DEER_FLOW_HOME"):
        return Path(env_home).resolve()
    return project_root() / ".deer-flow"


def resolve_path(value: str | os.PathLike[str], *, base: Path | None = None) -> Path:
    '''将相对路径相对于指定基准或项目根解析为绝对路径。'''
    path = Path(value)
    if not path.is_absolute():
        path = (base or project_root()) / path
    return path.resolve()


def existing_project_file(names: tuple[str, ...]) -> Path | None:
    '''按候选名称顺序查找项目根目录中的第一个现存文件。'''
    root = project_root()
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None
