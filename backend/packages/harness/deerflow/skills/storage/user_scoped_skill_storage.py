"""定义 user_scoped_skill_storage 模块提供的职责与可复用接口。

User-scoped SkillStorage that isolates custom skills per user.

Custom skills are stored under ``{base_dir}/users/{user_id}/skills/custom/``
instead of the global ``{base_dir}/skills/custom/``. Public skills are still
read from the global ``{base_dir}/skills/public/`` (read-only).

Layout::

    <host_root>/public/<name>/SKILL.md            ← global, read-only
    <user_custom_root>/<name>/SKILL.md             ← per-user, read-write
    <user_custom_root>/.history/<name>.jsonl       ← per-user history
    <user_skills_root>/_skill_states.json          ← per-user enabled state
    <global_custom_root>/<name>/SKILL.md           ← legacy fallback, read-only

Fallback: when a user has no custom skills yet, global ``skills/custom/``
skills are yielded as ``SkillCategory.LEGACY`` (read-only) so they are
visible but cannot be edited/deleted by the user. This preserves backward
compatibility during migration without leaking mutable access to legacy
skills. Legacy skills are mounted at ``/mnt/skills/legacy/<name>/`` in
the sandbox so their supporting files (references, templates, scripts,
assets) are accessible to the agent.

Enabled/disabled state for CUSTOM and LEGACY skills is stored per-user in
``_skill_states.json`` (keyed by skill name). PUBLIC skill state remains
global in ``extensions_config.json``. This prevents cross-user bleed when
two users own same-named custom skills.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.permissions import make_skill_written_path_sandbox_readable
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage, _iter_direct_skill_files
from deerflow.skills.storage.skill_storage import SKILL_MD_FILE
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)


class UserScopedSkillStorage(LocalSkillStorage):
    """用户隔离的技能仓储；自定义技能独立存放，公共技能共享只读。"""

    def __init__(
        self,
        user_id: str,
        host_path: str | None = None,
        container_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
        app_config=None,
    ) -> None:
        """校验用户标识并解析该用户的技能、历史和开关状态目录。"""
        super().__init__(host_path=host_path, container_path=container_path, app_config=app_config)

        from deerflow.config.paths import _validate_user_id, get_paths

        self._user_id = _validate_user_id(user_id)
        paths = get_paths()
        self._user_custom_root: Path = paths.user_custom_skills_dir(self._user_id)
        self._user_skills_root: Path = paths.user_skills_dir(self._user_id)
        self._global_custom_root: Path = self._host_root / SkillCategory.CUSTOM.value
        self._skill_states_file: Path = self._user_skills_root / "_skill_states.json"

    # ------------------------------------------------------------------
    # Per-user skill enabled state (CUSTOM / LEGACY only)
    # ------------------------------------------------------------------

    def _read_skill_states(self) -> dict[str, dict[str, bool]]:
        """读取用户技能开关；文件不存在、损坏或不可读时返回空映射。"""
        if not self._skill_states_file.exists():
            return {}
        try:
            with open(self._skill_states_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read skill states file %s", self._skill_states_file)
        return {}

    def _write_skill_states(self, states: dict[str, dict[str, bool]]) -> None:
        """将用户技能开关写入同目录临时文件，再替换正式文件以避免写坏原状态。"""
        self._user_skills_root.mkdir(parents=True, exist_ok=True)
        fd, tmp_path_str = tempfile.mkstemp(
            dir=str(self._user_skills_root),
            prefix=".skill_states_",
            suffix=".json.tmp",
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(states, f, indent=2)
            tmp_path.replace(self._skill_states_file)
        except Exception:
            # 写入失败时尽力移除未完成的临时文件。
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def get_skill_enabled_state(self, skill_name: str) -> bool:
        """读取自定义或旧技能的用户级开关；尚无记录时默认启用。"""
        states = self._read_skill_states()
        entry = states.get(skill_name)
        if entry is None:
            return True
        return entry.get("enabled", True)

    def set_skill_enabled_state(self, skill_name: str, enabled: bool) -> None:
        """更新指定技能的用户级启用状态并持久化。"""
        states = self._read_skill_states()
        states[skill_name] = {"enabled": enabled}
        self._write_skill_states(states)

    # ------------------------------------------------------------------
    # Path helpers — redirect custom skill paths to user directory
    # ------------------------------------------------------------------

    def get_custom_skill_dir(self, name: str) -> Path:
        """返回当前用户的自定义技能目录，不创建目录。"""
        normalized_name = self.validate_skill_name(name)
        return self._user_custom_root / normalized_name

    def get_custom_skill_file(self, name: str) -> Path:
        """返回当前用户技能的 `SKILL.md` 路径。"""
        return self.get_custom_skill_dir(name) / SKILL_MD_FILE

    def get_skill_history_file(self, name: str) -> Path:
        """返回当前用户该技能的 JSONL 历史文件路径。"""
        normalized_name = self.validate_skill_name(name)
        return self._user_custom_root / ".history" / f"{normalized_name}.jsonl"

    # ------------------------------------------------------------------
    # Enabled state — override to use per-user state for custom/legacy
    # ------------------------------------------------------------------

    def load_skills(self, *, enabled_only: bool = False) -> list:
        """发现技能后合并用户级开关；公共技能仍沿用全局启用配置。"""
        # 父类负责通用发现和公共技能状态合并，技能类别来源由迭代器决定。
        skills = super().load_skills(enabled_only=False)

        # 自定义和旧技能同时受全局默认值及用户开关约束，公共技能只遵循全局配置。
        from deerflow.config.extensions_config import get_extensions_config

        extensions_config = get_extensions_config()
        skills = [
            dataclasses.replace(s, enabled=self.get_skill_enabled_state(s.name) and extensions_config.is_skill_enabled(s.name, s.category.value if hasattr(s.category, "value") else s.category))
            if dataclasses.is_dataclass(s) and not isinstance(s, type) and (s.category.value if hasattr(s.category, "value") else s.category) != SkillCategory.PUBLIC.value
            else s
            for s in skills
        ]

        if enabled_only:
            skills = [s for s in skills if s.enabled]

        return skills

    # ------------------------------------------------------------------
    # Skill iteration — public from global, custom from user dir + fallback
    # ------------------------------------------------------------------

    def public_skill_exists(self, name: str) -> bool:
        """检查公共技能或全局旧技能是否存在，以便编辑操作返回正确的只读提示。"""
        normalized_name = self.validate_skill_name(name)
        # Standard public check
        if (self._host_root / SkillCategory.PUBLIC.value / normalized_name / SKILL_MD_FILE).exists():
            return True
        # Global custom fallback check (legacy skills visible to all users)
        if (self._global_custom_root / normalized_name / SKILL_MD_FILE).exists():
            return True
        return False

    def ensure_custom_skill_is_editable(self, name: str) -> None:
        """拒绝修改公共或迁移期旧技能，并提示用户创建同名个人技能。"""
        if self.custom_skill_exists(name):
            return
        # Check both public and global-custom fallback
        normalized_name = self.validate_skill_name(name)
        is_global_public = (self._host_root / SkillCategory.PUBLIC.value / normalized_name / SKILL_MD_FILE).exists()
        is_global_custom_fallback = (self._global_custom_root / normalized_name / SKILL_MD_FILE).exists()
        if is_global_public:
            raise ValueError(f"'{name}' is a built-in skill. Use the skill_manage tool to create your own version — it will shadow the built-in one.")
        if is_global_custom_fallback:
            raise ValueError(f"'{name}' is a legacy shared skill (not editable). To customise it, create your own version with the same name — it will shadow the shared one.")
        raise FileNotFoundError(f"Custom skill '{name}' not found.")

    def _iter_skill_files(self) -> Iterable[tuple[SkillCategory, Path, Path]]:
        """枚举全局公共技能、用户自定义技能及条件成立时的全局旧技能。"""
        # 公共技能始终来自共享技能根目录。
        public_path = self._host_root / SkillCategory.PUBLIC.value
        if public_path.exists() and public_path.is_dir():
            for skill_file in _iter_direct_skill_files(public_path):
                yield SkillCategory.PUBLIC, public_path, skill_file

        # 2. Custom skills: prefer user-level directory
        user_custom_exists = False
        user_custom_path = self._user_custom_root
        if user_custom_path.exists() and user_custom_path.is_dir():
            for skill_file in _iter_direct_skill_files(user_custom_path):
                user_custom_exists = True
                yield SkillCategory.CUSTOM, user_custom_path, skill_file

        # 3. Fallback: if user has no custom skills, load from global custom
        #    as LEGACY (read-only) so legacy skills are visible but not
        #    editable/deletable by the user. LEGACY skills are mounted at
        #    /mnt/skills/legacy/<name>/ in the sandbox so their supporting
        #    files (references, templates, scripts, assets) are accessible.
        if not user_custom_exists:
            global_custom_path = self._global_custom_root
            if global_custom_path.exists() and global_custom_path.is_dir():
                for skill_file in _iter_direct_skill_files(global_custom_path):
                    yield SkillCategory.LEGACY, global_custom_path, skill_file

    # ------------------------------------------------------------------
    # Install — redirect custom_dir to user directory
    # ------------------------------------------------------------------

    async def ainstall_skill_from_archive(self, archive_path: str | Path) -> dict:
        """将技能包安装到当前用户目录，并在提交前执行异步安全扫描。"""
        from deerflow.skills.installer import _scan_skill_archive_contents_or_raise

        logger.info("Installing skill from %s for user %s", archive_path, self._user_id)
        path = Path(archive_path)
        custom_dir = self._user_custom_root

        # 确保当前用户的自定义技能目录已建立。
        custom_dir.mkdir(parents=True, exist_ok=True)

        # 安全扫描包含异步模型调用；文件处理放到工作线程，避免阻塞事件循环。
        tmp = await asyncio.to_thread(tempfile.mkdtemp)
        try:
            skill_dir, skill_name, target = await asyncio.to_thread(self._prepare_skill_archive, path, Path(tmp), custom_dir, archive_path)

            await _scan_skill_archive_contents_or_raise(skill_dir, skill_name)

            await asyncio.to_thread(self._commit_skill_install, skill_dir, skill_name, custom_dir, target)
            logger.info("Skill %r installed to %s for user %s", skill_name, target, self._user_id)
        finally:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._cleanup_install_tmp, tmp),
                    timeout=5.0,
                )
            except TimeoutError:
                logger.warning("Timed out cleaning up skill install temp dir %s", tmp)

        return {
            "success": True,
            "skill_name": skill_name,
            "message": f"Skill '{skill_name}' installed successfully for user '{self._user_id}'",
        }

    # ------------------------------------------------------------------
    # Write — ensure user custom dir exists before writing
    # ------------------------------------------------------------------

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        """原子写入当前用户的技能文件，并设置沙箱可读取的文件权限。"""
        # 首次写入时创建用户技能目录。
        self._user_custom_root.mkdir(parents=True, exist_ok=True)
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

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def user_id(self) -> str:
        """返回此技能仓储绑定的规范化用户标识。"""
        return self._user_id

    def get_user_custom_root(self) -> Path:
        """返回当前用户自定义技能的宿主机根目录。"""
        return self._user_custom_root

    # ------------------------------------------------------------------
    # Path validation — accept per-user custom root as well as global root
    # ------------------------------------------------------------------

    def validate_skill_file_path(self, skill_file: Path) -> Path:
        """解析技能文件，并确认它位于全局根目录或当前用户技能根目录内。"""
        resolved_file = skill_file.resolve()
        for allowed_root in (self._host_root.resolve(), self._user_custom_root.resolve()):
            try:
                resolved_file.relative_to(allowed_root)
                return resolved_file
            except ValueError:
                continue
        raise ValueError(f"Resolved skill file {resolved_file} must stay within either the global skills root ({self._host_root.resolve()}) or the per-user custom root ({self._user_custom_root.resolve()}).")
