"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""
import logging
import os
import subprocess
from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox.local_backend import (
    LocalContainerBackend,
    _format_container_command_for_log,
    _format_container_mount,
    _redact_container_command_for_log,
    _resolve_docker_bind_host,
)


def test_format_container_mount_uses_mount_syntax_for_docker_windows_paths():
    """验证“格式容器挂载使用挂载该项该项容器运行时视窗系统该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    args = _format_container_mount("docker", "D:/deer-flow/backend/.deer-flow/threads", "/mnt/threads", False)

    assert args == [
        "--mount",
        "type=bind,src=D:/deer-flow/backend/.deer-flow/threads,dst=/mnt/threads",
    ]


def test_format_container_mount_marks_docker_readonly_mounts():
    """验证“格式容器挂载该项容器运行时该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    args = _format_container_mount("docker", "/host/path", "/mnt/path", True)

    assert args == [
        "--mount",
        "type=bind,src=/host/path,dst=/mnt/path,readonly",
    ]


def test_format_container_mount_keeps_volume_syntax_for_apple_container():
    """验证“格式容器挂载保留该项该项该项苹果容器运行时容器”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    args = _format_container_mount("container", "/host/path", "/mnt/path", True)

    assert args == [
        "-v",
        "/host/path:/mnt/path:ro",
    ]


def test_redact_container_command_for_log_redacts_env_values():
    """验证“脱敏容器命令该项该项该项环境变量该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    redacted = _redact_container_command_for_log(
        [
            "docker",
            "run",
            "-e",
            "API_KEY=secret-value",
            "--env=TOKEN=token-value",
            "--name",
            "sandbox",
            "image",
        ]
    )

    assert "API_KEY=<redacted>" in redacted
    assert "--env=TOKEN=<redacted>" in redacted
    assert "secret-value" not in " ".join(redacted)
    assert "token-value" not in " ".join(redacted)


def test_redact_container_command_for_log_keeps_inherited_env_names():
    """验证“脱敏容器命令该项该项保留该项环境变量该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    redacted = _redact_container_command_for_log(
        [
            "docker",
            "run",
            "-e",
            "API_KEY",
            "--env=TOKEN",
            "--name",
            "sandbox",
            "image",
        ]
    )

    assert redacted == [
        "docker",
        "run",
        "-e",
        "API_KEY",
        "--env=TOKEN",
        "--name",
        "sandbox",
        "image",
    ]


def test_format_container_command_for_log_uses_windows_quoting(monkeypatch):
    """验证“格式容器命令该项该项使用视窗系统该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setattr(os, "name", "nt")

    command = _format_container_command_for_log(["docker", "run", "--name", "sandbox one", "image"])

    assert command == 'docker run --name "sandbox one" image'


def test_start_container_logs_redacted_env_values(monkeypatch, caplog):
    """验证“启动容器该项该项环境变量该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={"API_KEY": "secret-value", "NORMAL": "visible-value"},
    )
    monkeypatch.setattr(backend, "_runtime", "docker")

    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    with caplog.at_level(logging.INFO, logger="deerflow.community.aio_sandbox.local_backend"):
        backend._start_container("sandbox-test", 18080)

    joined_cmd = " ".join(captured_cmd)
    assert "API_KEY=secret-value" in joined_cmd
    assert "NORMAL=visible-value" in joined_cmd

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert "API_KEY=<redacted>" in log_output
    assert "NORMAL=<redacted>" in log_output
    assert "secret-value" not in log_output
    assert "visible-value" not in log_output


def _capture_start_container_command(monkeypatch, backend: LocalContainerBackend, runtime: str = "docker") -> list[str]:
    """为“捕获启动容器命令”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    monkeypatch.setattr(backend, "_runtime", runtime)
    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend._start_container("sandbox-test", 18080)
    return captured_cmd


def test_resolve_docker_bind_host_defaults_loopback_for_localhost(monkeypatch):
    """验证“该项容器运行时该项主机该项回环该项本机”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_HOST", raising=False)

    assert _resolve_docker_bind_host() == "127.0.0.1"


def test_resolve_docker_bind_host_keeps_dood_compatibility(monkeypatch):
    """验证“该项容器运行时该项主机保留该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")

    assert _resolve_docker_bind_host() == "0.0.0.0"


def test_resolve_docker_bind_host_uses_ipv6_loopback_for_ipv6_sandbox_host(monkeypatch):
    """验证“该项容器运行时该项主机使用该项回环该项该项沙箱主机”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "[::1]")

    assert _resolve_docker_bind_host() == "[::1]"


def test_resolve_docker_bind_host_logs_selected_bind_reason(caplog):
    """验证“该项容器运行时该项主机该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    with caplog.at_level(logging.DEBUG, logger="deerflow.community.aio_sandbox.local_backend"):
        assert _resolve_docker_bind_host(sandbox_host="localhost", bind_host="") == "127.0.0.1"

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "Docker sandbox bind: 127.0.0.1 (loopback default)" in messages


def test_resolve_docker_bind_host_allows_explicit_override(monkeypatch):
    """验证“该项容器运行时该项主机允许显式该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "localhost")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "192.0.2.10")

    assert _resolve_docker_bind_host() == "192.0.2.10"


def test_start_container_binds_local_docker_port_to_loopback_by_default(monkeypatch):
    """验证“启动容器绑定本地容器运行时该项该项回环该项默认值”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.delenv("DEER_FLOW_SANDBOX_HOST", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("-p") + 1] == "127.0.0.1:18080:8080"


def test_start_container_keeps_broad_bind_for_dood_sandbox_host(monkeypatch):
    """验证“启动容器保留该项该项该项该项沙箱主机”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "host.docker.internal")
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("-p") + 1] == "0.0.0.0:18080:8080"


def test_start_container_binds_ipv6_sandbox_host_to_ipv6_loopback(monkeypatch):
    """验证“启动容器绑定该项沙箱主机该项该项回环”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.setenv("DEER_FLOW_SANDBOX_HOST", "[::1]")
    monkeypatch.delenv("DEER_FLOW_SANDBOX_BIND_HOST", raising=False)

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert captured_cmd[captured_cmd.index("-p") + 1] == "[::1]:18080:8080"


def test_start_container_keeps_apple_container_port_format(monkeypatch):
    """验证“启动容器保留苹果容器运行时容器该项格式”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    monkeypatch.setenv("DEER_FLOW_SANDBOX_BIND_HOST", "127.0.0.1")

    captured_cmd = _capture_start_container_command(monkeypatch, backend, runtime="container")

    assert captured_cmd[captured_cmd.index("-p") + 1] == "18080:8080"


def _backend_for_inspect_tests() -> LocalContainerBackend:
    """为“该项该项检查该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={},
    )
    backend._runtime = "docker"
    return backend


def test_is_container_running_false_when_container_missing(monkeypatch):
    """验证“该项容器运行中该项当容器缺失”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return SimpleNamespace(stdout="", stderr="Error: No such object: sandbox-missing", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend._is_container_running("sandbox-missing") is False


def test_is_container_running_raises_on_runtime_error(monkeypatch):
    """验证“该项容器运行中抛出该项运行时错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return SimpleNamespace(stdout="", stderr="Cannot connect to the Docker daemon", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Failed to inspect container sandbox-busy"):
        backend._is_container_running("sandbox-busy")


def test_is_container_running_raises_on_timeout(monkeypatch):
    """验证“该项容器运行中抛出该项超时”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Timed out checking container sandbox-timeout"):
        backend._is_container_running("sandbox-timeout")


def test_discover_returns_none_when_runtime_check_fails(monkeypatch):
    """验证“发现返回空值当运行时该项失败”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return SimpleNamespace(stdout="", stderr="Cannot connect to the Docker daemon", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend.discover("sandbox-blip") is None


def test_discover_returns_none_when_runtime_check_times_out(monkeypatch):
    """验证“发现返回空值当运行时该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend.discover("sandbox-timeout") is None


def test_is_container_running_false_on_apple_container_not_found(monkeypatch):
    """验证“该项容器运行中该项该项苹果容器运行时容器该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return SimpleNamespace(stdout="", stderr='Error: not found: "sandbox-apple"', returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert backend._is_container_running("sandbox-apple") is False


def test_is_container_running_raises_on_unrelated_not_found_error(monkeypatch):
    """验证“该项容器运行中抛出该项该项该项该项错误”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    backend = _backend_for_inspect_tests()

    def fake_run(cmd, **kwargs):
        """为“该项该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return SimpleNamespace(stdout="", stderr="Error: credential helper not found in $PATH", returncode=1)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Failed to inspect container sandbox-busy"):
        backend._is_container_running("sandbox-busy")
