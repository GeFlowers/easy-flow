"""提供配置、技能、配置相关功能。"""

import os
from pathlib import Path

from pydantic import BaseModel, Field

from deerflow.config.runtime_paths import project_root, resolve_path
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH


def _legacy_skills_candidates() -> tuple[Path, ...]:
    """\u6267\u884c _legacy_skills_candidates \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
    backend_dir = Path(__file__).resolve().parents[4]
    repo_root = backend_dir.parent
    return (repo_root / "skills",)


class SkillsConfig(BaseModel):
    """\u6267\u884c SkillsConfig \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""

    use: str = Field(
        default="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        description="Class path of the SkillStorage implementation.",
    )
    path: str | None = Field(
        default=None,
        description=("Path to skills directory. If not specified, defaults to `skills` under the caller project root, falling back to the legacy repo-root location for monorepo compatibility."),
    )
    container_path: str = Field(
        default=DEFAULT_SKILLS_CONTAINER_PATH,
        description="Path where skills are mounted in the sandbox container",
    )
    deferred_discovery: bool = Field(
        default=False,
        description=("When enabled, skill metadata is not injected into the system prompt. Instead, only skill names appear in <skill_index> and the LLM discovers details on demand via the describe_skill tool."),
    )

    def get_skills_path(self) -> Path:
        """\u6267\u884c get_skills_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        if self.path:
            # 中文说明：此处用于执行相关处理。
            return resolve_path(self.path)
        if env_path := os.getenv("DEER_FLOW_SKILLS_PATH"):
            return resolve_path(env_path)

        project_default = project_root() / "skills"
        if project_default.is_dir():
            return project_default

        for candidate in _legacy_skills_candidates():
            if candidate.is_dir():
                return candidate

        return project_default

    def get_skill_container_path(self, skill_name: str, category: str = "public") -> str:
        """\u6267\u884c get_skill_container_path \u5b9a\u4e49\u7684\u64cd\u4f5c\u3002"""
        return f"{self.container_path}/{category}/{skill_name}"
