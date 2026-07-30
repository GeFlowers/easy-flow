'未说明'

from pathlib import Path

import pytest

from deerflow.skills.package_paths import is_eval_fixture_skill_md
from deerflow.skills.validation import _validate_skill_frontmatter

SKILLS_PUBLIC_DIR = Path(__file__).resolve().parents[2] / "skills" / "public"


BUNDLED_SKILL_DIRS = sorted(p.parent for p in SKILLS_PUBLIC_DIR.rglob("SKILL.md") if not is_eval_fixture_skill_md(p.relative_to(SKILLS_PUBLIC_DIR)))


@pytest.mark.parametrize(
    "skill_dir",
    BUNDLED_SKILL_DIRS,
    ids=lambda p: str(p.relative_to(SKILLS_PUBLIC_DIR)),
)
def test_bundled_skill_frontmatter_is_valid(skill_dir: Path) -> None:
    '未说明'
    valid, msg, name = _validate_skill_frontmatter(skill_dir)
    assert valid, f"{skill_dir.relative_to(SKILLS_PUBLIC_DIR)}: {msg}"
    assert name, f"{skill_dir.relative_to(SKILLS_PUBLIC_DIR)}: no name extracted"


def test_skills_public_dir_has_skills() -> None:
    '未说明'
    assert BUNDLED_SKILL_DIRS, f"no SKILL.md found under {SKILLS_PUBLIC_DIR}"
