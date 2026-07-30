"""本模块覆盖读取 文件 工具的行为、边界与回归场景，确保既有契约稳定。"""

from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import read_file_tool


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


def test_read_file_tool_binary_file_returns_actionable_hint(tmp_path, monkeypatch) -> None:
    """验证读取 文件 工具 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
    runtime = _local_runtime(tmp_path)
    # .xlsx is a zip container: header bytes PK\x03\x04 plus a non-UTF-8 byte 0x82
    # that makes strict UTF-8 decoding fail (the exact byte seen in the field logs).
    (tmp_path / "uploads" / "data.xlsx").write_bytes(b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x82\x6a\xb1\x55")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = read_file_tool.func(
        runtime=runtime,
        description="read uploaded excel",
        path="/mnt/user-data/uploads/data.xlsx",
    )

    assert "Unexpected error" not in result, result
    assert "binary" in result.lower(), result
    # The model must be steered to bash + pandas/openpyxl, not another read_file.
    assert "bash" in result.lower(), result


def test_read_file_tool_text_file_unaffected(tmp_path, monkeypatch) -> None:
    """验证读取 文件 工具 文件在预期条件及边界场景下的可观察行为，防止相关回归。"""
    runtime = _local_runtime(tmp_path)
    (tmp_path / "uploads" / "notes.txt").write_text("hello 你好\nsecond line", encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = read_file_tool.func(
        runtime=runtime,
        description="read notes",
        path="/mnt/user-data/uploads/notes.txt",
    )

    assert "hello 你好" in result, result
    assert "binary" not in result.lower(), result
