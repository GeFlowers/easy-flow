'''定义技能元数据、来源类别、密钥声明及其容器内路径转换。'''

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH

SKILL_MD_FILE = "SKILL.md"


class SkillCategory(StrEnum):
    '''区分随项目提供、用户自建和迁移遗留的技能来源。

        - ``PUBLIC``：随平台提供的公共技能，只读。
        - ``CUSTOM``：用户自行创建的技能，允许编辑或删除。
        - ``LEGACY``：用户隔离之前的共享自定义技能，仅可读取，不可编辑或删除；
          沙箱通过 ``/mnt/skills/legacy/<name>/`` 路径提供这些技能的文件。
    '''

    PUBLIC = "public"
    CUSTOM = "custom"
    LEGACY = "legacy"


@dataclass(frozen=True)
class SecretRequirement:
    '''声明技能运行时需要的请求级密钥及其是否为可选项。'''

    name: str
    optional: bool = False


@dataclass(frozen=True)
class Skill:
    '''保存技能元数据、来源、启用状态和磁盘位置。'''

    name: str
    description: str
    license: str | None
    skill_dir: Path
    skill_file: Path
    relative_path: Path  # 技能目录相对于所属类别根目录的路径。
    category: SkillCategory  # 技能来源类别。
    allowed_tools: tuple[str, ...] | None = None
    enabled: bool = False  # 是否允许该技能进入运行时。
    required_secrets: tuple[SecretRequirement, ...] = field(default_factory=tuple)
    # 控制声明的密钥能否随模型自主加载技能而绑定；关闭时仅显式斜杠激活可绑定。
    secrets_autonomous: bool = True

    @property
    def skill_path(self) -> str:
        '''返回技能目录相对其来源类别根目录的规范路径。'''
        path = self.relative_path.as_posix()
        return "" if path == "." else path

    def get_container_path(self, container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH) -> str:
        '''根据技能类别、相对路径和容器挂载根目录计算技能目录路径。


        Args:
            container_base_path: 技能在容器中的挂载根目录。

        Returns:
            容器内的技能目录完整路径。
        '''
        category_base = f"{container_base_path}/{self.category}"
        skill_path = self.skill_path
        if skill_path:
            return f"{category_base}/{skill_path}"
        return category_base

    def get_container_file_path(self, container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH) -> str:
        '''根据技能目录路径计算其主说明文件 SKILL.md 的容器内路径。


        Args:
            container_base_path: 技能在容器中的挂载根目录。

        Returns:
            容器内 SKILL.md 的完整路径。
        '''
        return f"{self.get_container_path(container_base_path)}/SKILL.md"

    def __repr__(self) -> str:
        '''生成包含技能名称、描述和来源类别的调试表示。'''
        return f"Skill(name={self.name!r}, description={self.description!r}, category={self.category!r})"
