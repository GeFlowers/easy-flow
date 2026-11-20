'''读取全局代理指令。'''

from pathlib import Path

from deerflow.config.paths import get_paths

AGENTS_FILENAME = "AGENTS.md"


def load_project_agent_instructions() -> str | None:
    '''从运行数据根目录读取适用于所有智能体的指令。'''
    return _read_agent_instructions(get_paths().base_dir / AGENTS_FILENAME)


def load_default_agent_instructions() -> str | None:
    """读取默认主代理的提示词。"""
    return _read_agent_instructions(get_paths().default_agent_dir / AGENTS_FILENAME)


def _read_agent_instructions(path: Path) -> str | None:
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return content or None
