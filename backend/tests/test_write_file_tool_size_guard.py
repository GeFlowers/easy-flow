'未说明'

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deerflow.sandbox import tools as tools_module
from deerflow.sandbox.tools import write_file_tool


def _call_write_file(*, content: str, append: bool = False) -> str:
    '未说明'
    fn = getattr(write_file_tool, "func", write_file_tool)
    runtime = MagicMock()

    with (
        patch.object(tools_module, "ensure_sandbox_initialized") as mock_ensure,
        patch.object(tools_module, "ensure_thread_directories_exist"),
        patch.object(tools_module, "is_local_sandbox", return_value=False),
        patch.object(tools_module, "get_file_operation_lock") as mock_lock,
    ):
        sandbox = MagicMock()
        sandbox.write_file = MagicMock()
        mock_ensure.return_value = sandbox
        mock_lock.return_value.__enter__ = MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        return fn(
            runtime=runtime,
            description="test write",
            path="/tmp/test.txt",
            content=content,
            append=append,
        )


def test_below_cap_succeeds():
    '未说明'
    payload = "a" * (79 * 1024)
    result = _call_write_file(content=payload)
    assert result == "OK"


def test_above_cap_returns_actionable_error():
    '未说明'
    payload = "a" * (81 * 1024)
    result = _call_write_file(content=payload)

    assert result.startswith("Error: write_file content")
    assert "81920 bytes" in result or "82944 bytes" in result, "Error must report the actual content size so the LLM/operator can judge how much to trim or chunk."
    assert "str_replace" in result, "Error must point to str_replace as the preferred incremental-edit path."
    assert "append=True" in result, "Error must also surface the append-in-chunks alternative."


def test_above_cap_with_append_true_bypasses_guard():
    '未说明'
    payload = "a" * (200 * 1024)  # 200 KB
    result = _call_write_file(content=payload, append=True)
    assert result == "OK", f"append=True must bypass the size guard, got: {result!r}"


def test_env_override_raises_cap(monkeypatch: pytest.MonkeyPatch):
    '未说明'
    monkeypatch.setenv("DEERFLOW_WRITE_FILE_MAX_BYTES", str(300 * 1024))
    payload = "a" * (150 * 1024)  # 150 KB — would normally trip the 80 KB cap
    result = _call_write_file(content=payload)
    assert result == "OK"


def test_env_override_zero_disables_guard(monkeypatch: pytest.MonkeyPatch):
    '未说明'
    monkeypatch.setenv("DEERFLOW_WRITE_FILE_MAX_BYTES", "0")
    payload = "a" * (500 * 1024)  # 500 KB
    result = _call_write_file(content=payload)
    assert result == "OK"


def test_env_override_malformed_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    '未说明'
    monkeypatch.setenv("DEERFLOW_WRITE_FILE_MAX_BYTES", "lots")
    # 100 KB should still be rejected because the malformed value falls back
    # to the 80 KB default.
    payload = "a" * (100 * 1024)
    result = _call_write_file(content=payload)
    assert result.startswith("Error: write_file content")
