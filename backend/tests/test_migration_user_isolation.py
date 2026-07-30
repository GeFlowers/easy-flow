"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

import json
from pathlib import Path

import pytest

from deerflow.config.paths import Paths


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    return tmp_path


@pytest.fixture
def paths(base_dir: Path) -> Paths:
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    return Paths(base_dir)


class TestMigrateThreadDirs:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_moves_thread_to_user_dir(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy = base_dir / "threads" / "t1" / "user-data" / "workspace"
        legacy.mkdir(parents=True)
        (legacy / "file.txt").write_text("hello")

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"})

        expected = base_dir / "users" / "alice" / "threads" / "t1" / "user-data" / "workspace" / "file.txt"
        assert expected.exists()
        assert expected.read_text() == "hello"
        assert not (base_dir / "threads" / "t1").exists()

    def test_unowned_thread_goes_to_default(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy = base_dir / "threads" / "t2" / "user-data" / "workspace"
        legacy.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={})

        expected = base_dir / "users" / "default" / "threads" / "t2"
        assert expected.exists()

    def test_idempotent_skip_already_migrated(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        new_dir = base_dir / "users" / "alice" / "threads" / "t1" / "user-data" / "workspace"
        new_dir.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"})
        assert new_dir.exists()

    def test_conflict_preserved(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy = base_dir / "threads" / "t1" / "user-data" / "workspace"
        legacy.mkdir(parents=True)
        (legacy / "old.txt").write_text("old")

        dest = base_dir / "users" / "alice" / "threads" / "t1" / "user-data" / "workspace"
        dest.mkdir(parents=True)
        (dest / "new.txt").write_text("new")

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"})

        assert (dest / "new.txt").read_text() == "new"
        conflicts = base_dir / "migration-conflicts" / "t1"
        assert conflicts.exists()

    def test_cleans_up_empty_legacy_dir(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy = base_dir / "threads" / "t1" / "user-data"
        legacy.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={})

        assert not (base_dir / "threads").exists()

    def test_dry_run_does_not_move(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy = base_dir / "threads" / "t1" / "user-data"
        legacy.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        report = migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"}, dry_run=True)

        assert len(report) == 1
        assert (base_dir / "threads" / "t1").exists()  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert not (base_dir / "users" / "alice" / "threads" / "t1").exists()


class TestMigrateMemory:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_moves_global_memory(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy_mem = base_dir / "memory.json"
        legacy_mem.write_text(json.dumps({"version": "1.0", "facts": []}))

        from scripts.migrate_user_isolation import migrate_memory

        migrate_memory(paths, user_id="default")

        expected = base_dir / "users" / "default" / "memory.json"
        assert expected.exists()
        assert not legacy_mem.exists()

    def test_skips_if_destination_exists(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy_mem = base_dir / "memory.json"
        legacy_mem.write_text(json.dumps({"version": "old"}))

        dest = base_dir / "users" / "default" / "memory.json"
        dest.parent.mkdir(parents=True)
        dest.write_text(json.dumps({"version": "new"}))

        from scripts.migrate_user_isolation import migrate_memory

        migrate_memory(paths, user_id="default")

        assert json.loads(dest.read_text())["version"] == "new"
        assert (base_dir / "memory.legacy.json").exists()

    def test_no_legacy_memory_is_noop(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        from scripts.migrate_user_isolation import migrate_memory

        migrate_memory(paths, user_id="default")  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestMigrateAgents:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    @staticmethod
    def _seed_legacy_agent(paths: Paths, name: str, *, soul: str = "soul", description: str = "d") -> Path:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        legacy_dir = paths.agents_dir / name
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "config.yaml").write_text(f"name: {name}\ndescription: {description}\n", encoding="utf-8")
        (legacy_dir / "SOUL.md").write_text(soul, encoding="utf-8")
        return legacy_dir

    def test_moves_legacy_into_user_layout(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        self._seed_legacy_agent(paths, "agent-a", soul="soul-a")
        self._seed_legacy_agent(paths, "agent-b", soul="soul-b")

        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default")

        assert {entry["agent"] for entry in report} == {"agent-a", "agent-b"}
        for entry in report:
            assert entry["user_id"] == "default"
            assert "moved -> " in entry["action"]

        for name, soul in [("agent-a", "soul-a"), ("agent-b", "soul-b")]:
            dest = paths.user_agent_dir("default", name)
            assert dest.exists(), f"{name} should have moved into the per-user layout"
            assert (dest / "SOUL.md").read_text() == soul

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert not paths.agents_dir.exists()

    def test_dry_run_does_not_move(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy_dir = self._seed_legacy_agent(paths, "agent-a")

        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default", dry_run=True)

        assert len(report) == 1
        assert legacy_dir.exists(), "dry-run must not touch the filesystem"
        assert not paths.user_agent_dir("default", "agent-a").exists()

    def test_existing_destination_is_treated_as_conflict(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        self._seed_legacy_agent(paths, "agent-a", soul="legacy soul")
        dest = paths.user_agent_dir("default", "agent-a")
        dest.mkdir(parents=True)
        (dest / "SOUL.md").write_text("preexisting", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default")

        assert report[0]["action"].startswith("conflict -> ")
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert (dest / "SOUL.md").read_text() == "preexisting"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        conflicts_dir = paths.base_dir / "migration-conflicts" / "agents" / "agent-a"
        assert (conflicts_dir / "SOUL.md").read_text() == "legacy soul"

    def test_no_legacy_dir_is_noop(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default")
        assert report == []


class TestMigrateSkills:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    @staticmethod
    def _seed_legacy_skill(base_dir: Path, name: str, *, content: str = "skill doc") -> Path:
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        skill_dir = base_dir / "skills" / "custom" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return skill_dir

    def test_moves_legacy_into_user_layout(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        self._seed_legacy_skill(base_dir, "my-skill", content="legacy skill")
        (base_dir / "skills" / "public" / "bootstrap").mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default")

        assert len(report) == 1
        assert report[0]["skill"] == "my-skill"
        assert "moved -> " in report[0]["action"]

        dest = paths.user_custom_skills_dir("default") / "my-skill" / "SKILL.md"
        assert dest.exists()
        assert dest.read_text() == "legacy skill"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert not (base_dir / "skills" / "custom").exists()
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert (base_dir / "skills" / "public").exists()

    def test_dry_run_does_not_move(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        legacy_dir = self._seed_legacy_skill(base_dir, "my-skill")

        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default", dry_run=True)

        assert len(report) == 1
        assert legacy_dir.exists(), "dry-run must not touch the filesystem"
        assert not (paths.user_custom_skills_dir("default") / "my-skill").exists()

    def test_existing_destination_is_conflict(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        self._seed_legacy_skill(base_dir, "my-skill", content="legacy")
        dest = paths.user_custom_skills_dir("default") / "my-skill"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("preexisting", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default")

        assert report[0]["action"].startswith("conflict -> ")
        assert (dest / "SKILL.md").read_text() == "preexisting"
        conflicts_dir = paths.base_dir / "migration-conflicts" / "skills" / "my-skill"
        assert (conflicts_dir / "SKILL.md").read_text() == "legacy"

    def test_no_legacy_dir_is_noop(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default")
        assert report == []

    def test_migrates_history_dir(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        history_dir = base_dir / "skills" / "custom" / ".history"
        history_dir.mkdir(parents=True)
        (history_dir / "log.json").write_text("[]", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_skills

        migrate_skills(paths, user_id="default")

        dest_history = paths.user_custom_skills_dir("default") / ".history" / "log.json"
        assert dest_history.exists()
        assert not history_dir.exists()

    def test_skills_parent_dir_not_deleted_even_if_custom_empty(self, base_dir: Path, paths: Paths):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        (base_dir / "skills" / "custom").mkdir(parents=True)
        (base_dir / "skills" / "public" / "bootstrap").mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_skills

        migrate_skills(paths, user_id="default")

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert not (base_dir / "skills" / "custom").exists()
        assert (base_dir / "skills").exists()
        assert (base_dir / "skills" / "public").exists()
