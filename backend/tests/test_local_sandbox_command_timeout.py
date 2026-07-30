"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

import os
import shlex
import sys
import time
from pathlib import Path

import pytest

from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.local import local_sandbox
from deerflow.sandbox.local.local_sandbox import LocalSandbox

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
linux_proc_fd_only = pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="requires Linux /proc fd links")


@posix_only
def test_backgrounded_process_returns_promptly():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox = LocalSandbox("t")
    start = time.monotonic()
    output = sandbox.execute_command("sleep 5 & echo serving", timeout=10)
    elapsed = time.monotonic() - start

    assert elapsed < 3, f"expected prompt return, took {elapsed:.1f}s"
    assert "serving" in output


@posix_only
@linux_proc_fd_only
def test_backgrounded_process_does_not_inherit_deleted_temp_capture(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    marker = tmp_path / "fd1"
    script = f"import os, pathlib, time; pathlib.Path({str(marker)!r}).write_text(os.readlink('/proc/self/fd/1')); time.sleep(2)"
    sandbox = LocalSandbox("t")

    output = sandbox.execute_command(f"{shlex.quote(sys.executable)} -c {shlex.quote(script)} & echo launched", timeout=10)

    assert "launched" in output
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()
    assert " (deleted)" not in marker.read_text()


@posix_only
def test_foreground_blocking_command_times_out_with_notice():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox = LocalSandbox("t")
    start = time.monotonic()
    output = sandbox.execute_command("while true; do sleep 0.2; done", timeout=1)
    elapsed = time.monotonic() - start

    assert elapsed < 5, f"timeout not enforced, took {elapsed:.1f}s"
    assert "timed out" in output.lower()


def test_timeout_notice_formats_fractional_and_singular_timeouts(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setattr(LocalSandbox, "_get_shell", lambda self: "/bin/sh")
    monkeypatch.setattr(LocalSandbox, "_run_posix_command", staticmethod(lambda args, timeout, env=None: ("", "", 0, True)))

    assert "after 1.5 seconds" in LocalSandbox("t").execute_command("wait", timeout=1.5)
    assert "after 1 second" in LocalSandbox("t").execute_command("wait", timeout=1)


def test_windows_timeout_expired_returns_notice(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    def fake_run(*args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        raise local_sandbox.subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"], output="partial out", stderr="partial err")

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(LocalSandbox, "_get_shell", lambda self: "cmd.exe")
    monkeypatch.setattr(local_sandbox.subprocess, "run", fake_run)

    output = LocalSandbox("t").execute_command("wait", timeout=1.5)

    assert "partial out" in output
    assert "Std Error:" in output
    assert "partial err" in output
    assert "after 1.5 seconds" in output
    assert "Unexpected error" not in output


@posix_only
def test_foreground_timeout_kills_whole_process_group(tmp_path):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    marker = tmp_path / "alive"
    sandbox = LocalSandbox("t")
    sandbox.execute_command(f"while true; do touch {marker}; sleep 0.2; done", timeout=1)

    assert marker.exists()
    first_mtime = marker.stat().st_mtime
    time.sleep(1.5)
    assert marker.stat().st_mtime == first_mtime, "process group survived the timeout"


@posix_only
def test_command_reading_stdin_does_not_block():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox = LocalSandbox("t")
    start = time.monotonic()
    output = sandbox.execute_command("read x; echo got", timeout=10)
    elapsed = time.monotonic() - start

    assert elapsed < 3, f"stdin read blocked, took {elapsed:.1f}s"
    assert "got" in output


@posix_only
def test_normal_command_output_exit_code_and_stderr():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    sandbox = LocalSandbox("t")

    assert "hello" in sandbox.execute_command("echo hello")
    assert "Exit Code: 3" in sandbox.execute_command("exit 3")

    combined = sandbox.execute_command("echo out; echo oops >&2")
    assert "out" in combined
    assert "Std Error:" in combined
    assert "oops" in combined


def test_sandbox_config_exposes_command_timeout_default():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")
    assert cfg.bash_command_timeout == 600


def test_sandbox_config_exposes_health_check_skip_seconds_default():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    cfg = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")
    assert cfg.health_check_skip_seconds is None


def test_bash_tool_description_guides_backgrounding_long_lived_processes():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.sandbox.tools import bash_tool

    description = bash_tool.description.lower()
    assert "background" in description
    assert "server" in description
