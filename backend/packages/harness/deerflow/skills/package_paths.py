'未说明'

from __future__ import annotations

from pathlib import PurePosixPath


def _parts(path: str | PurePosixPath) -> tuple[str, ...]:
    '未说明'
    return PurePosixPath(str(path).replace("\\", "/")).parts


def is_eval_fixture_path(path: str | PurePosixPath) -> bool:
    '未说明'
    parts = _parts(path)
    for index, part in enumerate(parts[:-1]):
        if part == "evals" and len(parts) > index + 2:
            return parts[index + 1] == "fixtures"
    return False


def is_eval_fixture_skill_md(path: str | PurePosixPath) -> bool:
    '未说明'
    parts = _parts(path)
    return bool(parts) and parts[-1] == "SKILL.md" and is_eval_fixture_path(PurePosixPath(*parts[:-1]))
