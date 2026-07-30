"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.sandbox.local import local_sandbox as local_sandbox_module
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping


def _make_sandbox(tmp_path: Path) -> LocalSandbox:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    ws = tmp_path / "workspace"
    skills = tmp_path / "skills"
    ws.mkdir()
    skills.mkdir()
    return LocalSandbox(
        id="test",
        path_mappings=[
            PathMapping(container_path="/mnt/user-data/workspace", local_path=str(ws)),
            PathMapping(container_path="/mnt/skills", local_path=str(skills), read_only=True),
        ],
    )


def test_patterns_are_compiled_once_and_cached(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sb._command_pattern is sb._command_pattern
    assert sb._content_pattern is sb._content_pattern
    assert sb._reverse_output_patterns is sb._reverse_output_patterns
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert len(sb._reverse_output_patterns) == 2


def test_empty_mappings_yield_no_pattern(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = LocalSandbox(id="empty", path_mappings=[])
    assert sb._command_pattern is None
    assert sb._content_pattern is None
    assert sb._reverse_output_patterns == []
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sb._resolve_paths_in_command("echo hello") == "echo hello"
    assert sb._resolve_paths_in_content("plain text") == "plain text"


def test_command_paths_resolved_to_local(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    ws_local = str((tmp_path / "workspace").resolve())
    out = sb._resolve_paths_in_command("cat /mnt/user-data/workspace/foo.txt")
    assert out == f"cat {ws_local}/foo.txt"
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sb._resolve_paths_in_command("cat /mnt/user-data/workspace/foo.txt") == out


def test_segment_boundary_not_matched_inside_longer_name(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    out = sb._resolve_paths_in_command("ls /mnt/skills-extra/data")
    assert out == "ls /mnt/skills-extra/data"


def test_reverse_resolve_output_maps_local_back_to_container(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    ws_local = str((tmp_path / "workspace").resolve())
    out = sb._reverse_resolve_paths_in_output(f"wrote {ws_local}/foo.txt ok")
    assert out == "wrote /mnt/user-data/workspace/foo.txt ok"


@pytest.mark.parametrize("suffix", ["-extra/data.txt", "2/x", ".bak", "foo", "_backup/y"])
def test_reverse_resolve_does_not_match_inside_longer_sibling(tmp_path, suffix):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())
    sibling = f"{skills_local}{suffix}"

    out = sb._reverse_resolve_paths_in_output(f"see {sibling}")

    assert out == f"see {sibling}"
    assert "/mnt/skills" not in out


@pytest.mark.parametrize(
    ("trailer", "expected_trailer"),
    [
        (", ok", ", ok"),  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        (":/other", ":/other"),  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        ("\\win\\p", "/win/p"),  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        (" done", " done"),  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        ("' ", "' "),  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    ],
)
def test_reverse_resolve_still_matches_root_before_non_slash_boundaries(tmp_path, trailer, expected_trailer):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())

    out = sb._reverse_resolve_paths_in_output(f"{skills_local}{trailer}")

    assert out == f"/mnt/skills{expected_trailer}"


@pytest.mark.parametrize("prefix", ["", "cwd: ", "see "])
def test_reverse_resolve_translates_a_bare_root_at_end_of_output(tmp_path, prefix):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())

    out = sb._reverse_resolve_paths_in_output(f"{prefix}{skills_local}")

    assert out == f"{prefix}/mnt/skills"
    assert skills_local not in out


def test_reverse_resolve_path_matches_windows_backslash_containment(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = LocalSandbox(
        id="windows-sep-test",
        path_mappings=[
            PathMapping(container_path="/mnt/user-data/workspace", local_path="C:\\Users\\test\\workspace"),
        ],
    )
    mapping = sb.path_mappings[0]

    monkeypatch.setattr(local_sandbox_module.os, "sep", "\\")
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    sb._resolved_local_paths = {mapping: "C:\\Users\\test\\workspace"}

    class _FakeWindowsPath:
        """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

        def __init__(self, raw: str) -> None:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            self._raw = raw

        def resolve(self) -> _FakeWindowsPath:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return _FakeWindowsPath(self._raw.replace("/", "\\"))

        def __str__(self) -> str:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            return self._raw

    monkeypatch.setattr(local_sandbox_module, "Path", _FakeWindowsPath)

    result = sb._reverse_resolve_path("C:\\Users\\test\\workspace\\sub\\f.txt")

    assert result == "/mnt/user-data/workspace/sub/f.txt"


def test_resolved_paths_and_sorted_views_are_cached(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sb._resolved_local_paths is sb._resolved_local_paths
    assert sb._mappings_by_container_specificity is sb._mappings_by_container_specificity
    assert sb._mappings_by_local_specificity is sb._mappings_by_local_specificity
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert set(sb._resolved_local_paths.values()) == {
        str((tmp_path / "workspace").resolve()),
        str((tmp_path / "skills").resolve()),
    }
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sb._mappings_by_container_specificity[0].container_path == "/mnt/user-data/workspace"


def test_forward_resolution_behavior_unchanged(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    ws_local = str((tmp_path / "workspace").resolve())
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sb._resolve_path("/mnt/user-data/workspace/sub/foo.txt") == f"{ws_local}/sub/foo.txt"
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    assert sb._resolve_path("/etc/hosts") == "/etc/hosts"


def test_read_only_mount_detected(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sb = _make_sandbox(tmp_path)
    skills_local = str((tmp_path / "skills").resolve())
    ws_local = str((tmp_path / "workspace").resolve())
    assert sb._is_read_only_path(f"{skills_local}/a.md") is True
    assert sb._is_read_only_path(f"{ws_local}/a.txt") is False
