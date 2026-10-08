'''统一技能包路径处理，并识别评测夹具以便从实际技能扫描中排除。'''

from __future__ import annotations

from pathlib import PurePosixPath


def _parts(path: str | PurePosixPath) -> tuple[str, ...]:
    '''把 Windows 或 POSIX 路径写法统一拆成 POSIX 路径组件。'''
    return PurePosixPath(str(path).replace("\\", "/")).parts


def is_eval_fixture_path(path: str | PurePosixPath) -> bool:
    '''判断路径是否位于 evals/fixtures 子树中。'''
    parts = _parts(path)
    for index, part in enumerate(parts[:-1]):
        if part == "evals" and len(parts) > index + 2:
            return parts[index + 1] == "fixtures"
    return False


def is_eval_fixture_skill_md(path: str | PurePosixPath) -> bool:
    '''判断位于评测夹具目录中的 SKILL.md，避免把样例误认作嵌套技能。'''
    parts = _parts(path)
    return bool(parts) and parts[-1] == "SKILL.md" and is_eval_fixture_path(PurePosixPath(*parts[:-1]))
