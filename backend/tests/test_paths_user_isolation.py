"""本模块覆盖用户 隔离的行为、边界与回归场景，确保既有契约稳定。"""

from pathlib import Path

import pytest

from deerflow.config.paths import Paths


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    """准备可控测试资源与状态，供后续断言读取。"""
    return Paths(tmp_path)


class TestValidateUserId:
    """集中覆盖当前测试分支与回归边界。"""
    def test_valid_user_id(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        d = paths.user_dir("u-abc-123")
        assert d == paths.base_dir / "users" / "u-abc-123"

    def test_rejects_path_traversal(self, paths: Paths):
        """验证路径在预期条件及边界场景下的可观察行为，防止相关回归。"""
        with pytest.raises(ValueError, match="Invalid user_id"):
            paths.user_dir("../escape")

    def test_rejects_slash(self, paths: Paths):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        with pytest.raises(ValueError, match="Invalid user_id"):
            paths.user_dir("foo/bar")

    def test_rejects_empty(self, paths: Paths):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        with pytest.raises(ValueError, match="Invalid user_id"):
            paths.user_dir("")


class TestMakeSafeUserId:
    """集中覆盖当前测试分支与回归边界。"""
    def test_already_safe_id_is_unchanged(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.config.paths import make_safe_user_id

        assert make_safe_user_id("ou_abc-123") == "ou_abc-123"
        assert make_safe_user_id("123456") == "123456"

    def test_unsafe_chars_are_sanitized_with_stable_suffix(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.config.paths import make_safe_user_id

        result = make_safe_user_id("user@example.com")
        # Sanitized prefix plus a stable digest of the original.
        assert result.startswith("user-example-com-")
        assert len(result.rsplit("-", 1)[1]) == 16
        assert result == "user-example-com-b4c9a289323b21a0"
        assert make_safe_user_id("user@example.com") == result

    def test_sanitized_id_passes_validation(self, paths: Paths):
        """验证校验在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.config.paths import make_safe_user_id

        safe = make_safe_user_id("用户/../etc")
        # Must be usable as a filesystem-scoped bucket without raising.
        assert paths.user_dir(safe) == paths.base_dir / "users" / safe

    def test_distinct_unsafe_ids_do_not_collide(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.config.paths import make_safe_user_id

        assert make_safe_user_id("a.b") != make_safe_user_id("a/b")

    def test_empty_id_rejected(self):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        from deerflow.config.paths import make_safe_user_id

        with pytest.raises(ValueError, match="non-empty"):
            make_safe_user_id("")


class TestUserDir:
    """集中覆盖当前测试分支与回归边界。"""
    def test_user_dir(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert paths.user_dir("alice") == paths.base_dir / "users" / "alice"

    def test_prepare_user_dir_migrates_unique_legacy_unsafe_bucket(self, paths: Paths):
        """验证用户 唯一在预期条件及边界场景下的可观察行为，防止相关回归。"""
        from deerflow.config.paths import make_safe_user_id

        raw = "user@example.com"
        safe = make_safe_user_id(raw)
        legacy_dir = paths.base_dir / "users" / "user-example-com-63a710569261a24b"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "memory.json").write_text('{"legacy": true}\n', encoding="utf-8")

        assert paths.prepare_user_dir_for_raw_id(raw) == safe

        current_dir = paths.user_dir(safe)
        assert current_dir.exists()
        assert not legacy_dir.exists()
        assert (current_dir / "memory.json").read_text(encoding="utf-8") == '{"legacy": true}\n'

    def test_prepare_user_dir_never_migrates_another_users_bucket(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        import hashlib

        from deerflow.config.paths import make_safe_user_id

        users_dir = paths.base_dir / "users"
        other_legacy = users_dir / f"a-b-{hashlib.sha1(b'a/b').hexdigest()[:16]}"
        other_legacy.mkdir(parents=True)
        arbitrary_16_hex = users_dir / "a-b-1111111111111111"
        arbitrary_16_hex.mkdir(parents=True)

        assert paths.prepare_user_dir_for_raw_id("a.b") == make_safe_user_id("a.b")

        assert not paths.user_dir(make_safe_user_id("a.b")).exists()
        assert other_legacy.exists()
        assert arbitrary_16_hex.exists()


class TestUserMemoryFile:
    """集中覆盖当前测试分支与回归边界。"""
    def test_user_memory_file(self, paths: Paths):
        """验证用户 内存 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert paths.user_memory_file("bob") == paths.base_dir / "users" / "bob" / "memory.json"


class TestUserAgentMemoryFile:
    """集中覆盖当前测试分支与回归边界。"""
    def test_user_agent_memory_file(self, paths: Paths):
        """验证用户 内存 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "users" / "bob" / "agents" / "myagent" / "memory.json"
        assert paths.user_agent_memory_file("bob", "myagent") == expected

    def test_user_agent_memory_file_lowercases_name(self, paths: Paths):
        """验证用户 内存 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "users" / "bob" / "agents" / "myagent" / "memory.json"
        assert paths.user_agent_memory_file("bob", "MyAgent") == expected


class TestUserAgentDir:
    """集中覆盖当前测试分支与回归边界。"""
    def test_user_agents_dir(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert paths.user_agents_dir("alice") == paths.base_dir / "users" / "alice" / "agents"

    def test_user_agent_dir(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert paths.user_agent_dir("alice", "code-reviewer") == paths.base_dir / "users" / "alice" / "agents" / "code-reviewer"

    def test_user_agent_dir_lowercases_name(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        assert paths.user_agent_dir("alice", "CodeReviewer") == paths.base_dir / "users" / "alice" / "agents" / "codereviewer"

    def test_user_agent_dir_validates_user_id(self, paths: Paths):
        """验证用户 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        with pytest.raises(ValueError, match="Invalid user_id"):
            paths.user_agent_dir("../escape", "myagent")


class TestUserThreadDir:
    """集中覆盖当前测试分支与回归边界。"""
    def test_user_thread_dir(self, paths: Paths):
        """验证用户 会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1"
        assert paths.thread_dir("t1", user_id="u1") == expected

    def test_thread_dir_no_user_id_falls_back_to_legacy(self, paths: Paths):
        """验证会话 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "threads" / "t1"
        assert paths.thread_dir("t1") == expected


class TestUserSandboxDirs:
    """集中覆盖当前测试分支与回归边界。"""
    def test_sandbox_work_dir(self, paths: Paths):
        """验证沙箱在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data" / "workspace"
        assert paths.sandbox_work_dir("t1", user_id="u1") == expected

    def test_sandbox_uploads_dir(self, paths: Paths):
        """验证沙箱在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data" / "uploads"
        assert paths.sandbox_uploads_dir("t1", user_id="u1") == expected

    def test_sandbox_outputs_dir(self, paths: Paths):
        """验证沙箱在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data" / "outputs"
        assert paths.sandbox_outputs_dir("t1", user_id="u1") == expected

    def test_sandbox_user_data_dir(self, paths: Paths):
        """验证沙箱 用户 数据在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data"
        assert paths.sandbox_user_data_dir("t1", user_id="u1") == expected

    def test_acp_workspace_dir(self, paths: Paths):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "acp-workspace"
        assert paths.acp_workspace_dir("t1", user_id="u1") == expected

    def test_legacy_sandbox_work_dir(self, paths: Paths):
        """验证沙箱在预期条件及边界场景下的可观察行为，防止相关回归。"""
        expected = paths.base_dir / "threads" / "t1" / "user-data" / "workspace"
        assert paths.sandbox_work_dir("t1") == expected


class TestHostPathsWithUserId:
    """集中覆盖当前测试分支与回归边界。"""
    def test_host_thread_dir_with_user_id(self, paths: Paths):
        """验证会话 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        result = paths.host_thread_dir("t1", user_id="u1")
        assert "users" in result
        assert "u1" in result
        assert "threads" in result
        assert "t1" in result

    def test_host_thread_dir_legacy(self, paths: Paths):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        result = paths.host_thread_dir("t1")
        assert "threads" in result
        assert "t1" in result
        assert "users" not in result

    def test_host_sandbox_user_data_dir_with_user_id(self, paths: Paths):
        """验证沙箱 用户 数据 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        result = paths.host_sandbox_user_data_dir("t1", user_id="u1")
        assert "users" in result
        assert "user-data" in result

    def test_host_sandbox_work_dir_with_user_id(self, paths: Paths):
        """验证沙箱 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        result = paths.host_sandbox_work_dir("t1", user_id="u1")
        assert "workspace" in result

    def test_host_sandbox_uploads_dir_with_user_id(self, paths: Paths):
        """验证沙箱 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        result = paths.host_sandbox_uploads_dir("t1", user_id="u1")
        assert "uploads" in result

    def test_host_sandbox_outputs_dir_with_user_id(self, paths: Paths):
        """验证沙箱 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        result = paths.host_sandbox_outputs_dir("t1", user_id="u1")
        assert "outputs" in result

    def test_host_acp_workspace_dir_with_user_id(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        result = paths.host_acp_workspace_dir("t1", user_id="u1")
        assert "acp-workspace" in result


class TestEnsureAndDeleteWithUserId:
    """集中覆盖当前测试分支与回归边界。"""
    def test_ensure_thread_dirs_creates_user_scoped(self, paths: Paths):
        """验证会话 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        paths.ensure_thread_dirs("t1", user_id="u1")
        assert paths.sandbox_work_dir("t1", user_id="u1").is_dir()
        assert paths.sandbox_uploads_dir("t1", user_id="u1").is_dir()
        assert paths.sandbox_outputs_dir("t1", user_id="u1").is_dir()
        assert paths.acp_workspace_dir("t1", user_id="u1").is_dir()

    def test_delete_thread_dir_removes_user_scoped(self, paths: Paths):
        """验证会话 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        paths.ensure_thread_dirs("t1", user_id="u1")
        assert paths.thread_dir("t1", user_id="u1").exists()
        paths.delete_thread_dir("t1", user_id="u1")
        assert not paths.thread_dir("t1", user_id="u1").exists()

    def test_delete_thread_dir_idempotent(self, paths: Paths):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        paths.delete_thread_dir("nonexistent", user_id="u1")  # should not raise

    def test_ensure_thread_dirs_legacy_still_works(self, paths: Paths):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        paths.ensure_thread_dirs("t1")
        assert paths.sandbox_work_dir("t1").is_dir()

    def test_user_scoped_and_legacy_are_independent(self, paths: Paths):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        paths.ensure_thread_dirs("t1", user_id="u1")
        paths.ensure_thread_dirs("t1")
        # Both exist independently
        assert paths.thread_dir("t1", user_id="u1").exists()
        assert paths.thread_dir("t1").exists()
        # Delete one doesn't affect the other
        paths.delete_thread_dir("t1", user_id="u1")
        assert not paths.thread_dir("t1", user_id="u1").exists()
        assert paths.thread_dir("t1").exists()


class TestResolveVirtualPathWithUserId:
    """集中覆盖当前测试分支与回归边界。"""
    def test_resolve_virtual_path_with_user_id(self, paths: Paths):
        """验证路径 用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        paths.ensure_thread_dirs("t1", user_id="u1")
        result = paths.resolve_virtual_path("t1", "/mnt/user-data/workspace/file.txt", user_id="u1")
        expected_base = paths.sandbox_user_data_dir("t1", user_id="u1").resolve()
        assert str(result).startswith(str(expected_base))

    def test_resolve_virtual_path_legacy(self, paths: Paths):
        """验证路径在预期条件及边界场景下的可观察行为，防止相关回归。"""
        paths.ensure_thread_dirs("t1")
        result = paths.resolve_virtual_path("t1", "/mnt/user-data/workspace/file.txt")
        expected_base = paths.sandbox_user_data_dir("t1").resolve()
        assert str(result).startswith(str(expected_base))
