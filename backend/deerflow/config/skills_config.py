'''定义内置与用户技能存储位置，以及技能在沙箱中的虚拟路径。'''

import os
from pathlib import Path

from pydantic import BaseModel, Field

from deerflow.config.runtime_paths import project_root, resolve_path
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH


def _legacy_skills_candidates() -> tuple[Path, ...]:
    '''返回仓库旧版布局中可回退读取的技能目录候选项。'''
    backend_dir = Path(__file__).resolve().parents[2]
    repo_root = backend_dir.parent
    return (repo_root / "skills",)


class SkillsConfig(BaseModel):
    '''配置技能存储实现、主机目录和沙箱内技能挂载路径。'''

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
        description="Virtual path where skills are available inside the sandbox",
    )
    deferred_discovery: bool = Field(
        default=False,
        description=("When enabled, skill metadata is not injected into the system prompt. Instead, only skill names appear in <skill_index> and the LLM discovers details on demand via the describe_skill tool."),
    )

    def get_skills_path(self) -> Path:
        '''解析技能目录配置；未设置时优先使用项目默认目录再回退旧布局。'''
        if self.path:
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
        '''返回技能目录在沙箱命名空间中的规范绝对路径。'''
        return f"{self.container_path}/{category}/{skill_name}"
