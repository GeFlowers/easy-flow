'''使用本地文件系统实现技能发现、编辑、安装和历史记录操作。'''

from __future__ import annotations

import asyncio
import errno
import json
import logging
import shutil
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from deerflow.config.runtime_paths import resolve_path
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.permissions import make_skill_written_path_sandbox_readable
from deerflow.skills.storage.skill_storage import SKILL_MD_FILE, SkillStorage
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)

_INSTALL_TMP_CLEANUP_TIMEOUT_SECONDS = 5.0


def _iter_direct_skill_files(category_path: Path) -> Iterable[Path]:
    '''仅枚举目标目录直属子文件夹中的 SKILL.md，不递归进入嵌套目录。'''
    for skill_dir in sorted(category_path.iterdir(), key=lambda path: path.name):
        if skill_dir.name.startswith(".") or not skill_dir.is_dir():
            continue
        skill_file = skill_dir / SKILL_MD_FILE
        if skill_file.is_file():
            yield skill_file


class LocalSkillStorage(SkillStorage):
    '''本地文件系统技能仓储，公共技能只读、自定义技能可编辑并记录历史。'''

    def __init__(
        self,
        host_path: str | None = None,
        container_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
        app_config=None,
    ) -> None:
        '''根据配置或显式宿主机路径确定技能根目录。'''
        super().__init__(container_path=container_path)
        if host_path is None:
            from deerflow.config import get_app_config

            config = app_config or get_app_config()
            self._app_config = config
            self._host_root: Path = config.skills.get_skills_path()
        else:
            self._app_config = app_config
            self._host_root = resolve_path(host_path)


    def get_skills_root_path(self) -> Path:
        '''返回当前实例使用的宿主机技能根目录。'''
        return self._host_root

    def custom_skill_exists(self, name: str) -> bool:
        '''检查自定义技能说明文件是否存在。'''
        return self.get_custom_skill_file(name).exists()

    def public_skill_exists(self, name: str) -> bool:
        '''检查公共技能说明文件是否存在。'''
        normalized_name = self.validate_skill_name(name)
        return (self._host_root / SkillCategory.PUBLIC.value / normalized_name / SKILL_MD_FILE).exists()

    def _iter_skill_files(self) -> Iterable[tuple[SkillCategory, Path, Path]]:
        '''逐类别枚举直属技能目录中的说明文件，不递归扫描子目录。'''
        if not self._host_root.exists():
            return
        for category in SkillCategory:
            category_path = self._host_root / category.value
            if not category_path.exists() or not category_path.is_dir():
                continue
            for skill_file in _iter_direct_skill_files(category_path):
                yield category, category_path, skill_file

    def read_custom_skill(self, name: str) -> str:
        '''读取自定义技能说明文件；技能不存在时抛出文件未找到错误。'''
        if not self.custom_skill_exists(name):
            raise FileNotFoundError(f"Custom skill '{name}' not found.")
        return (self.get_custom_skill_dir(name) / SKILL_MD_FILE).read_text(encoding="utf-8")

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        '''在自定义技能目录内原子写入文件，并调整权限以供沙箱读取。'''
        target = self.validate_relative_path(relative_path, self.get_custom_skill_dir(name))
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(target.parent),
        ) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)
        tmp_path.replace(target)
        make_skill_written_path_sandbox_readable(self.get_custom_skill_dir(name), target)

    async def ainstall_skill_from_archive(self, archive_path: str | Path) -> dict:
        '''在线程池中处理文件操作、异步扫描技能包并提交安装结果。'''
        from deerflow.skills.installer import _scan_skill_archive_contents_or_raise

        logger.info("Installing skill from %s", archive_path)
        path = Path(archive_path)
        custom_dir = self._host_root / "custom"

        # 文件安全扫描包含异步模型调用，需留在事件循环；其余文件操作放入工作线程。
        tmp = await asyncio.to_thread(tempfile.mkdtemp)
        try:
            skill_dir, skill_name, target = await asyncio.to_thread(self._prepare_skill_archive, path, Path(tmp), custom_dir, archive_path)

            await _scan_skill_archive_contents_or_raise(skill_dir, skill_name, app_config=self._app_config)

            await asyncio.to_thread(self._commit_skill_install, skill_dir, skill_name, custom_dir, target)
            logger.info("Skill %r installed to %s", skill_name, target)
        finally:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._cleanup_install_tmp, tmp),
                    timeout=_INSTALL_TMP_CLEANUP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning("Timed out cleaning up skill install temp dir %s", tmp)

        return {
            "success": True,
            "skill_name": skill_name,
            "message": f"Skill '{skill_name}' installed successfully",
        }

    @staticmethod
    def _cleanup_install_tmp(tmp: str) -> None:
        '''尽力清理安装临时目录；清理失败只记日志，不覆盖安装结果。'''
        try:
            shutil.rmtree(tmp)
        except OSError:
            logger.warning("Failed to clean up skill install temp dir %s", tmp, exc_info=True)

    def _prepare_skill_archive(self, path: Path, tmp_path: Path, custom_dir: Path, archive_path: str | Path) -> tuple[Path, str, Path]:
        '''解压并校验技能归档，返回技能目录、名称及最终安装目标路径。'''
        import zipfile

        from deerflow.skills.installer import (
            SkillAlreadyExistsError,
            resolve_skill_dir_from_archive,
            safe_extract_skill_archive,
            scan_archive_preflight_or_raise,
        )
        from deerflow.skills.validation import _validate_skill_frontmatter

        if not path.is_file():
            if not path.exists():
                raise FileNotFoundError(f"Skill file not found: {archive_path}")
            raise ValueError(f"Path is not a file: {archive_path}")
        if path.suffix != ".skill":
            raise ValueError("File must have .skill extension")

        custom_dir.mkdir(parents=True, exist_ok=True)

        try:
            zf = zipfile.ZipFile(path, "r")
        except FileNotFoundError:
            raise FileNotFoundError(f"Skill file not found: {archive_path}") from None
        except (zipfile.BadZipFile, IsADirectoryError):
            raise ValueError("File is not a valid ZIP archive") from None

        with zf:
            scan_archive_preflight_or_raise(path, app_config=self._app_config)
            safe_extract_skill_archive(zf, tmp_path)

        skill_dir = resolve_skill_dir_from_archive(tmp_path)

        is_valid, message, skill_name = _validate_skill_frontmatter(skill_dir)
        if not is_valid:
            raise ValueError(f"Invalid skill: {message}")
        if not skill_name or "/" in skill_name or "\\" in skill_name or ".." in skill_name:
            raise ValueError(f"Invalid skill name: {skill_name}")

        target = custom_dir / skill_name
        if target.exists():
            raise SkillAlreadyExistsError(f"Skill '{skill_name}' already exists")

        return skill_dir, skill_name, target

    def _commit_skill_install(self, skill_dir: Path, skill_name: str, custom_dir: Path, target: Path) -> None:
        '''将已校验技能复制到暂存目录，再原子移入目标位置并设置沙箱可读权限。'''
        from deerflow.skills.installer import _move_staged_skill_into_reserved_target

        with tempfile.TemporaryDirectory(prefix=f".installing-{skill_name}-", dir=custom_dir) as staging_root:
            staging_target = Path(staging_root) / skill_name
            shutil.copytree(skill_dir, staging_target)
            _move_staged_skill_into_reserved_target(staging_target, target)
        make_skill_written_path_sandbox_readable(custom_dir, target)

    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        '''验证技能可编辑后删除其目录；若提供元数据，先尽力保存删除前内容。'''
        self.validate_skill_name(name)
        self.ensure_custom_skill_is_editable(name)
        target = self.get_custom_skill_dir(name)
        if history_meta is not None:
            prev_content = self.read_custom_skill(name)
            try:
                self.append_history(name, {**history_meta, "prev_content": prev_content})
            except OSError as e:
                if not isinstance(e, PermissionError) and e.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
                    raise
                logger.warning(
                    "Skipping delete history write for custom skill %s due to readonly/permission failure; continuing with skill directory removal: %s",
                    name,
                    e,
                )
        if target.exists():
            shutil.rmtree(target)

    def append_history(self, name: str, record: dict) -> None:
        '''给历史记录补充 UTC 时间戳并追加到技能 JSONL 历史文件。'''
        self.validate_skill_name(name)
        payload = {"ts": datetime.now(UTC).isoformat(), **record}
        history_path = self.get_skill_history_file(name)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
            f.write("\n")

    def read_history(self, name: str) -> list[dict]:
        '''读取并解析技能 JSONL 历史；历史文件不存在时返回空列表。'''
        self.validate_skill_name(name)
        history_path = self.get_skill_history_file(name)
        if not history_path.exists():
            return []
        records: list[dict] = []
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records
