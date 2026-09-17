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
    """封装 UserScopedSkillStorage 的状态、协作关系与公开操作。

    Skill storage with per-user isolation for custom skills.

        Inherits all public-skill behaviour from :class:`LocalSkillStorage`
        (reading from ``_host_root/public/``). Custom-skill paths are
        redirected to ``_user_custom_root`` so each user's custom skills
        live in their own directory tree.

        Fallback: when the user's custom directory is empty and the global
        ``skills/custom/`` has content, those legacy skills are loaded as
        ``SkillCategory.LEGACY`` — they appear in listings but are treated
        as read-only (cannot be edited/deleted). This preserves backward
        compatibility during migration without giving users mutable access
        to other users' legacy skills.

        **Design note**: once a user creates their first custom skill, the
        per-user directory exists and the global custom fallback no longer
        applies — LEGACY skills disappear from that user's listing. This is
        intentional (shadow-mount semantics: the user's own directory
        shadows the global one).
    """

    def __init__(
        self,
        user_id: str,
        host_path: str | None = None,
        container_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
        app_config=None,
    ) -> None:
        "实现 __init__ 协议方法，保持对象交互语义一致"
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
        """执行 _read_skill_states 的明确职责，并返回与调用约定一致的结果。

        Read per-user skill enabled states from ``_skill_states.json``.

                Returns a dict keyed by skill name, each value being
                ``{"enabled": True/False}``.  Returns an empty dict if the file
                does not exist or is unreadable.
        """
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
        """执行 _write_skill_states 的明确职责，并返回与调用约定一致的结果。

        Persist per-user skill enabled states to ``_skill_states.json``.

                Atomic write via a temp file in the same directory followed by
                ``Path.replace`` (POSIX-atomic on the same filesystem). Without this,
                a crash/SIGTERM/disk-full mid-write would leave the file truncated
                or empty; ``_read_skill_states`` would then return ``{}`` and
                ``get_skill_enabled_state`` would silently re-enable every skill
                the user had disabled. Mirrors the pattern used by
                ``LocalSkillStorage.write_custom_skill`` in this same module.
        """
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
            # Best-effort cleanup of the temp file on failure.
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def get_skill_enabled_state(self, skill_name: str) -> bool:
        """读取并返回，并遵守 get_skill_enabled_state 所表达的接口约束。

        Return the enabled state for a custom/legacy skill.

                Default is ``True`` (newly created skills are enabled by default).
        """
        states = self._read_skill_states()
        entry = states.get(skill_name)
        if entry is None:
            return True
        return entry.get("enabled", True)

    def set_skill_enabled_state(self, skill_name: str, enabled: bool) -> None:
        """执行 set_skill_enabled_state 的明确职责，并返回与调用约定一致的结果。

        Set the enabled state for a custom/legacy skill and persist."""
        states = self._read_skill_states()
        states[skill_name] = {"enabled": enabled}
        self._write_skill_states(states)

    # ------------------------------------------------------------------
    # Path helpers — redirect custom skill paths to user directory
    # ------------------------------------------------------------------

    def get_custom_skill_dir(self, name: str) -> Path:
        """读取并返回，并遵守 get_custom_skill_dir 所表达的接口约束。

        Per-user custom skill directory: ``<user_custom_root>/<name>/``."""
        normalized_name = self.validate_skill_name(name)
        return self._user_custom_root / normalized_name

    def get_custom_skill_file(self, name: str) -> Path:
        """读取并返回，并遵守 get_custom_skill_file 所表达的接口约束。

        Per-user custom SKILL.md path."""
        return self.get_custom_skill_dir(name) / SKILL_MD_FILE

    def get_skill_history_file(self, name: str) -> Path:
        """读取并返回，并遵守 get_skill_history_file 所表达的接口约束。

        Per-user custom skill history: ``<user_custom_root>/.history/<name>.jsonl``."""
        normalized_name = self.validate_skill_name(name)
        return self._user_custom_root / ".history" / f"{normalized_name}.jsonl"

    # ------------------------------------------------------------------
    # Enabled state — override to use per-user state for custom/legacy
    # ------------------------------------------------------------------

    def load_skills(self, *, enabled_only: bool = False) -> list:
        """加载并返回，并遵守 load_skills 所表达的接口约束。

        Discover all skills and merge enabled state per isolation scope.

                Delegates skill discovery and PUBLIC enabled-state to
                :meth:`LocalSkillStorage.load_skills` (which reads from the
                overridden ``_iter_skill_files``).  Then overrides CUSTOM/LEGACY
                enabled state with per-user ``_skill_states.json`` so that two
                users each owning a same-named custom skill can toggle independently.

                Calling ``super().load_skills()`` preserves the full template-method
                flow (discover → global enabled-state merge → filter → sort) so
                that patching ``LocalSkillStorage.load_skills`` in tests still
                intercepts the call.
        """
        # Let the parent do full discovery + global enabled-state merge.
        # The overridden _iter_skill_files() routes custom reads to
        # _user_custom_root and legacy reads to _global_custom_root.
        skills = super().load_skills(enabled_only=False)

        # Override enabled state for CUSTOM / LEGACY with per-user state,
        # ANDed with the global extensions_config default. This preserves a
        # pre-upgrade global disable of a shared custom/legacy skill from
        # being silently re-enabled by an absent per-user entry, while still
        # letting the per-user state override the global default when both
        # are present. PUBLIC skill state remains governed solely by
        # extensions_config (handled by ``super().load_skills`` above).
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
        """执行 public_skill_exists 的明确职责，并返回与调用约定一致的结果。

        Check if a skill exists as public **or** as a global-custom fallback.

                The global ``skills/custom/`` directory contains legacy skills that
                are presented as ``SkillCategory.LEGACY`` to users who have no
                per-user custom skills yet. This override ensures those skills are
                recognised as "read-only" so ``ensure_custom_skill_is_editable``
                can give a helpful error message instead of ``FileNotFoundError``.
        """
        normalized_name = self.validate_skill_name(name)
        # Standard public check
        if (self._host_root / SkillCategory.PUBLIC.value / normalized_name / SKILL_MD_FILE).exists():
            return True
        # Global custom fallback check (legacy skills visible to all users)
        if (self._global_custom_root / normalized_name / SKILL_MD_FILE).exists():
            return True
        return False

    def ensure_custom_skill_is_editable(self, name: str) -> None:
        """执行 ensure_custom_skill_is_editable 的明确职责，并返回与调用约定一致的结果。

        Override to handle global-custom fallback skills gracefully.

                When a user tries to edit/delete a legacy global-custom skill (one
                that appears as ``SkillCategory.LEGACY`` due to fallback), we tell
                them to create their own version rather than raising a confusing
                ``FileNotFoundError``.
        """
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
        # 1. Public skills: always from global root
        "执行 _iter_skill_files 的明确职责，并返回与调用约定一致的结果"
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
        "执行 ainstall_skill_from_archive 的明确职责，并返回与调用约定一致的结果"
        from deerflow.skills.installer import _scan_skill_archive_contents_or_raise

        logger.info("Installing skill from %s for user %s", archive_path, self._user_id)
        path = Path(archive_path)
        custom_dir = self._user_custom_root

        # Ensure user custom directory exists
        custom_dir.mkdir(parents=True, exist_ok=True)

        # The per-file security scan is an async LLM call and must stay on the
        # event loop; every filesystem phase around it runs in a worker thread.
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
        # Ensure user custom skills directory exists
        "执行 write_custom_skill 的明确职责，并返回与调用约定一致的结果"
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
        """执行 user_id 的明确职责，并返回与调用约定一致的结果。

        The user ID this storage is scoped to."""
        return self._user_id

    def get_user_custom_root(self) -> Path:
        """读取并返回，并遵守 get_user_custom_root 所表达的接口约束。

        Host path to this user's custom skills root directory."""
        return self._user_custom_root

    # ------------------------------------------------------------------
    # Path validation — accept per-user custom root as well as global root
    # ------------------------------------------------------------------

    def validate_skill_file_path(self, skill_file: Path) -> Path:
        """校验输入并在约束不满足时报告错误，并遵守 validate_skill_file_path 所表达的接口约束。

        Accept files under *either* the global root or the per-user custom root.

                Custom skills live in ``_user_custom_root`` which is not a sub-path
                of ``_host_root``, so the default implementation's single-root check
                would reject them.  This override allows both roots.
        """
        resolved_file = skill_file.resolve()
        for allowed_root in (self._host_root.resolve(), self._user_custom_root.resolve()):
            try:
                resolved_file.relative_to(allowed_root)
                return resolved_file
            except ValueError:
                continue
        raise ValueError(f"Resolved skill file {resolved_file} must stay within either the global skills root ({self._host_root.resolve()}) or the per-user custom root ({self._user_custom_root.resolve()}).")
