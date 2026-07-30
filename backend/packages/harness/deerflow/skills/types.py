'定义 types 模块提供的职责与可复用接口'
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH

SKILL_MD_FILE = "SKILL.md"


class SkillCategory(StrEnum):
    '封装 SkillCategory 的状态、协作关系与公开操作。\n\nSource category for a skill.\n\n    - ``PUBLIC``: built-in skill bundled with the platform, read-only.\n    - ``CUSTOM``: user-authored skill that can be edited or deleted.\n    - ``LEGACY``: global custom skill from before user-isolation migration,\n      presented as read-only (visible but not editable/deletable). These\n      skills are mounted at ``/mnt/skills/legacy/<name>/`` in the sandbox.\n    '

    PUBLIC = "public"
    CUSTOM = "custom"
    LEGACY = "legacy"


@dataclass(frozen=True)
class SecretRequirement:
    "封装 SecretRequirement 的状态、协作关系与公开操作。\n\nA request-scoped secret a skill declares it needs (issue #3861).\n\n    ``name`` is both the key looked up in the request's ``context.secrets`` and\n    the environment variable name injected into the skill's sandbox subprocess\n    when the skill is activated.\n    "

    name: str
    optional: bool = False


@dataclass(frozen=True)
class Skill:
    '封装 Skill 的状态、协作关系与公开操作。\n\nRepresents a skill with its metadata and file path'

    name: str
    description: str
    license: str | None
    skill_dir: Path
    skill_file: Path
    relative_path: Path  # Relative path from category root to skill directory
    category: SkillCategory  # 'public' or 'custom'
    allowed_tools: tuple[str, ...] | None = None
    enabled: bool = False  # Whether this skill is enabled
    required_secrets: tuple[SecretRequirement, ...] = field(default_factory=tuple)
    # Whether declared secrets may bind when the skill is in-context via an
    # autonomous model load (skill_context), or only on explicit /slash
    # activation. Frontmatter: ``secrets-autonomous`` (default true).
    secrets_autonomous: bool = True

    @property
    def skill_path(self) -> str:
        "执行 skill_path 的明确职责，并返回与调用约定一致的结果。\n\nReturns the relative path from the category root (skills/{category}) to this skill's directory"
        path = self.relative_path.as_posix()
        return "" if path == "." else path

    def get_container_path(self, container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH) -> str:
        '读取并返回，并遵守 get_container_path 所表达的接口约束。\n\n\n        Get the full path to this skill in the container.\n\n        Args:\n            container_base_path: Base path where skills are mounted in the container\n\n        Returns:\n            Full container path to the skill directory\n        '
        category_base = f"{container_base_path}/{self.category}"
        skill_path = self.skill_path
        if skill_path:
            return f"{category_base}/{skill_path}"
        return category_base

    def get_container_file_path(self, container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH) -> str:
        "读取并返回，并遵守 get_container_file_path 所表达的接口约束。\n\n\n        Get the full path to this skill's main file (SKILL.md) in the container.\n\n        Args:\n            container_base_path: Base path where skills are mounted in the container\n\n        Returns:\n            Full container path to the skill's SKILL.md file\n        "
        return f"{self.get_container_path(container_base_path)}/SKILL.md"

    def __repr__(self) -> str:
        '实现 __repr__ 协议方法，保持对象交互语义一致'
        return f"Skill(name={self.name!r}, description={self.description!r}, category={self.category!r})"
