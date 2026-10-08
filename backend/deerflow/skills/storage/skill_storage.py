'''定义技能存储的统一接口、路径校验和跨后端通用流程。'''

from __future__ import annotations

import dataclasses
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.types import SKILL_MD_FILE, Skill, SkillCategory  # noqa: F401

logger = logging.getLogger(__name__)

_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillStorage(ABC):
    '''技能存储抽象基类：由后端实现原子读写，本类组合通用校验与发现流程。'''

    def __init__(self, container_path: str = DEFAULT_SKILLS_CONTAINER_PATH) -> None:
        '''保存智能体可访问的技能虚拟目录路径。'''
        self._container_root = container_path


    @staticmethod
    def validate_skill_name(name: str) -> str:
        '''校验技能名格式与长度，并返回去除首尾空白后的名称。'''
        normalized = name.strip()
        if not _SKILL_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("Skill name must be hyphen-case using lowercase letters, digits, and hyphens only.")
        if len(normalized) > 64:
            raise ValueError("Skill name must be 64 characters or fewer.")
        return normalized

    @staticmethod
    def validate_relative_path(relative_path: str, base_dir: Path) -> Path:
        '''解析技能相对路径并校验最终目标仍位于技能根目录内。'''
        if not relative_path:
            raise ValueError("relative_path must not be empty.")
        resolved_base = base_dir.resolve()
        target = (resolved_base / relative_path).resolve()
        try:
            target.relative_to(resolved_base)
        except ValueError as exc:
            raise ValueError("relative_path must resolve within the skill directory.") from exc
        return target

    @staticmethod
    def validate_skill_markdown_content(name: str, content: str) -> None:
        '''解析技能说明文件的头部元数据，并验证其中名称与目标技能一致。'''
        import tempfile

        from deerflow.skills.validation import _validate_skill_frontmatter

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_skill_dir = Path(tmp_dir) / SkillStorage.validate_skill_name(name)
            temp_skill_dir.mkdir(parents=True, exist_ok=True)
            (temp_skill_dir / SKILL_MD_FILE).write_text(content, encoding="utf-8")
            is_valid, message, parsed_name = _validate_skill_frontmatter(temp_skill_dir)
            if not is_valid:
                raise ValueError(message)
            if parsed_name != name:
                raise ValueError(f"Frontmatter name '{parsed_name}' must match requested skill name '{name}'.")

    def ensure_safe_support_path(self, name: str, relative_path: str) -> Path:
        '''校验技能附件只能位于允许的支持目录，并返回解析后的绝对路径。'''
        _ALLOWED_SUPPORT_SUBDIRS = {"references", "templates", "scripts", "assets"}
        skill_dir = self.get_custom_skill_dir(self.validate_skill_name(name)).resolve()
        if not relative_path or relative_path.endswith("/"):
            raise ValueError("Supporting file path must include a filename.")
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ValueError("Supporting file path must be relative.")
        if any(part in {"..", ""} for part in relative.parts):
            raise ValueError("Supporting file path must not contain parent-directory traversal.")
        top_level = relative.parts[0] if relative.parts else ""
        if top_level not in _ALLOWED_SUPPORT_SUBDIRS:
            raise ValueError(f"Supporting files must live under one of: {', '.join(sorted(_ALLOWED_SUPPORT_SUBDIRS))}.")
        target = (skill_dir / relative).resolve()
        allowed_root = (skill_dir / top_level).resolve()
        try:
            target.relative_to(allowed_root)
        except ValueError as exc:
            raise ValueError("Supporting file path must stay within the selected support directory.") from exc
        return target


    @abstractmethod
    def get_skills_root_path(self) -> Path:
        '''返回宿主机技能根目录，供发现技能和配置沙箱挂载使用。'''

    def validate_skill_file_path(self, skill_file: Path) -> Path:
        '''解析技能文件路径，并拒绝超出当前存储后端允许根目录的路径。'''
        resolved_file = skill_file.resolve()
        resolved_root = self.get_skills_root_path().resolve()
        try:
            resolved_file.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("Resolved skill file must stay within the configured skills root.") from exc
        return resolved_file

    @abstractmethod
    def _iter_skill_files(self) -> Iterable[tuple[SkillCategory, Path, Path]]:
        '''枚举技能类别、类别根目录及其直属技能的 `SKILL.md` 路径。'''

    @abstractmethod
    def read_custom_skill(self, name: str) -> str:
        '''读取指定自定义技能的 `SKILL.md` 正文。'''

    @abstractmethod
    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        '''将文本原子写入指定自定义技能目录内的相对路径。'''

    @abstractmethod
    async def ainstall_skill_from_archive(self, archive_path: str | Path) -> dict:
        '''异步校验并安装 `.skill` ZIP 包中的自定义技能。'''

    def install_skill_from_archive(self, archive_path: str | Path) -> dict:
        '''提供同步安装入口，并将异步安装流程交给专用运行器执行。'''
        from deerflow.skills.installer import _run_async_install

        return _run_async_install(self.ainstall_skill_from_archive(archive_path))

    @abstractmethod
    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        '''验证技能归属后删除自定义技能目录，并按配置保存变更历史。

        由网关的 ``delete_custom_skill`` 接口或 ``skill_manage_tool`` 工具调用。
        '''

    @abstractmethod
    def custom_skill_exists(self, name: str) -> bool:
        '''检查自定义技能目录中是否存在该技能的说明文件。'''

    @abstractmethod
    def public_skill_exists(self, name: str) -> bool:
        '''检查公共技能目录中是否存在该技能的说明文件。'''

    @abstractmethod
    def append_history(self, name: str, record: dict) -> None:
        '''为指定技能追加一条 JSONL 变更历史记录。'''

    @abstractmethod
    def read_history(self, name: str) -> list[dict]:
        '''按写入顺序读取指定技能的全部历史记录。'''


    def get_container_root(self) -> str:
        '''返回智能体可访问的技能虚拟目录根路径。'''
        return self._container_root

    def get_custom_skill_dir(self, name: str) -> Path:
        '''返回指定自定义技能目录；仅计算路径，不创建目录。'''
        normalized_name = self.validate_skill_name(name)
        return self.get_skills_root_path() / SkillCategory.CUSTOM.value / normalized_name

    def get_custom_skill_file(self, name: str) -> Path:
        '''返回指定自定义技能的 `SKILL.md` 路径。'''
        normalized_name = self.validate_skill_name(name)
        return self.get_custom_skill_dir(normalized_name) / SKILL_MD_FILE

    def get_skill_history_file(self, name: str) -> Path:
        '''返回自定义技能历史文件路径；隔离用户目录的后端应覆盖此实现。'''
        normalized_name = self.validate_skill_name(name)
        return self.get_skills_root_path() / SkillCategory.CUSTOM.value / ".history" / f"{normalized_name}.jsonl"


    def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
        '''解析所有已发现技能，合并扩展配置中的启用状态并按名称排序。'''
        from deerflow.skills.parser import parse_skill_file

        skills_by_name: dict[str, Skill] = {}
        for category, category_root, md_path in self._iter_skill_files():
            skill = parse_skill_file(
                md_path,
                category=category,
                relative_path=md_path.parent.relative_to(category_root),
            )
            if skill:
                skills_by_name[skill.name] = skill

        skills = list(skills_by_name.values())

        # 每次重新读取扩展配置，以便及时发现其他进程对技能启用状态的修改。
        # 各类别均遵循显式开关；未配置开关的自定义技能默认启用。
        try:
            from deerflow.config.extensions_config import ExtensionsConfig

            extensions_config = ExtensionsConfig.from_file()
            skills = [dataclasses.replace(s, enabled=extensions_config.is_skill_enabled(s.name, s.category)) for s in skills]
        except Exception as e:
            logger.warning("Failed to load extensions config: %s", e)

        if enabled_only:
            skills = [s for s in skills if s.enabled]

        skills.sort(key=lambda s: s.name)
        return skills

    def ensure_custom_skill_is_editable(self, name: str) -> None:
        '''确认技能属于可编辑的自定义类别；公共技能只读且会给出另建技能的提示。'''
        if self.custom_skill_exists(name):
            return
        if self.public_skill_exists(name):
            raise ValueError(f"'{name}' is a built-in skill. To customise it, create a new skill with the same name under skills/custom/.")
        raise FileNotFoundError(f"Custom skill '{name}' not found.")
