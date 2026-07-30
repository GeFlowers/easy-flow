"""本模块覆盖读取 文件的行为、边界与回归场景，确保既有契约稳定。"""

from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import read_file_tool

_FIVE_LINES = "line1\nline2\nline3\nline4\nline5"


def _local_runtime(tmp_path: Path) -> SimpleNamespace:
    """准备可控测试资源与状态，供后续断言读取。"""
    for sub in ("workspace", "uploads", "outputs"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    thread_data = {
        "workspace_path": str(tmp_path / "workspace"),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(tmp_path / "outputs"),
    }
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local:t1"}, "thread_data": thread_data},
        context={"thread_id": "t1"},
    )


def _read(tmp_path, monkeypatch, **kwargs) -> str:
    """准备可控测试资源与状态，供后续断言读取。"""
    runtime = _local_runtime(tmp_path)
    (tmp_path / "uploads" / "five.txt").write_text(_FIVE_LINES, encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    return read_file_tool.func(
        runtime=runtime,
        description="read a line range",
        path="/mnt/user-data/uploads/five.txt",
        **kwargs,
    )


def test_only_start_line_returns_tail_from_that_line(tmp_path, monkeypatch) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    result = _read(tmp_path, monkeypatch, start_line=3)
    assert result == "line3\nline4\nline5"


def test_only_end_line_returns_head_up_to_that_line(tmp_path, monkeypatch) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    result = _read(tmp_path, monkeypatch, end_line=2)
    assert result == "line1\nline2"


def test_start_line_zero_is_clamped_to_first_line(tmp_path, monkeypatch) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    result = _read(tmp_path, monkeypatch, start_line=0)
    assert result == _FIVE_LINES


def test_start_line_greater_than_end_line_returns_clean_error(tmp_path, monkeypatch) -> None:
    """验证错误在预期条件及边界场景下的可观察行为，防止相关回归。"""
    result = _read(tmp_path, monkeypatch, start_line=4, end_line=2)
    assert "start_line > end_line" in result
    # No garbage slice content leaked into the error.
    assert "line4" not in result


def test_start_line_beyond_eof_returns_clean_error(tmp_path, monkeypatch) -> None:
    """验证错误在预期条件及边界场景下的可观察行为，防止相关回归。"""
    result = _read(tmp_path, monkeypatch, start_line=99)
    assert "start_line exceeds file length" in result


def test_both_bounds_still_slice_inclusive_range(tmp_path, monkeypatch) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    result = _read(tmp_path, monkeypatch, start_line=2, end_line=4)
    assert result == "line2\nline3\nline4"


def test_only_end_line_zero_returns_clean_error(tmp_path, monkeypatch) -> None:
    """验证错误在预期条件及边界场景下的可观察行为，防止相关回归。"""
    result = _read(tmp_path, monkeypatch, end_line=0)
    assert "end_line must be >= 1" in result
    # No leaked line content in the error.
    assert "line1" not in result


def test_only_end_line_negative_returns_clean_error(tmp_path, monkeypatch) -> None:
    """验证错误在预期条件及边界场景下的可观察行为，防止相关回归。"""
    result = _read(tmp_path, monkeypatch, end_line=-1)
    assert "end_line must be >= 1" in result
    assert "line4" not in result


def test_end_line_past_eof_clamps_to_last_line(tmp_path, monkeypatch) -> None:
    """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
    result = _read(tmp_path, monkeypatch, end_line=99)
    assert result == _FIVE_LINES
