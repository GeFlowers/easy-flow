"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.gateway import deps as gateway_deps
from app.gateway.deps import get_config
from deerflow.config.app_config import (
    AppConfig,
    pop_current_app_config,
    push_current_app_config,
    reset_app_config,
    set_app_config,
)
from deerflow.config.sandbox_config import SandboxConfig


@pytest.fixture(autouse=True)
def _isolate_app_config_singleton():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    reset_app_config()
    yield
    reset_app_config()


def _write_config_yaml(path: Path, *, log_level: str) -> None:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    path.write_text(
        f"""
sandbox:
  use: deerflow.sandbox.local.provider:LocalSandboxProvider
log_level: {log_level}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _build_app() -> FastAPI:
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    app = FastAPI()

    @app.get("/probe")
    def probe(cfg: AppConfig = Depends(get_config)):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        return {"log_level": cfg.log_level}

    return app


def test_get_config_reflects_file_mtime_reload(tmp_path, monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    app = _build_app()
    client = TestClient(app)
    assert client.get("/probe").json() == {"log_level": "info"}

    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    _write_config_yaml(config_file, log_level="debug")
    future_mtime = config_file.stat().st_mtime + 5
    os.utime(config_file, (future_mtime, future_mtime))

    assert client.get("/probe").json() == {"log_level": "debug"}


def test_get_config_respects_runtime_context_override(tmp_path, monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    override = AppConfig(sandbox=SandboxConfig(use="test"), log_level="trace")
    push_current_app_config(override)
    try:
        app = _build_app()
        client = TestClient(app)
        assert client.get("/probe").json() == {"log_level": "trace"}
    finally:
        pop_current_app_config()


def test_get_config_respects_test_set_app_config():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    injected = AppConfig(sandbox=SandboxConfig(use="test"), log_level="warning")
    set_app_config(injected)

    app = _build_app()
    client = TestClient(app)
    assert client.get("/probe").json() == {"log_level": "warning"}


def test_run_context_app_config_reflects_yaml_edit(tmp_path, monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from unittest.mock import MagicMock

    from app.gateway.deps import get_run_context

    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    app = FastAPI()
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    app.state.checkpointer = MagicMock()
    app.state.store = MagicMock()
    app.state.run_event_store = MagicMock()
    app.state.run_events_config = {"frozen": "startup"}
    app.state.thread_store = MagicMock()

    @app.get("/run-ctx-log-level")
    def probe(ctx=Depends(get_run_context)):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        return {
            "log_level": ctx.app_config.log_level,
            "run_events_config": ctx.run_events_config,
        }

    client = TestClient(app)
    first = client.get("/run-ctx-log-level").json()
    assert first == {"log_level": "info", "run_events_config": {"frozen": "startup"}}

    _write_config_yaml(config_file, log_level="debug")
    future_mtime = config_file.stat().st_mtime + 5
    os.utime(config_file, (future_mtime, future_mtime))

    second = client.get("/run-ctx-log-level").json()
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert second == {"log_level": "debug", "run_events_config": {"frozen": "startup"}}


@pytest.mark.parametrize(
    "exception",
    [
        FileNotFoundError("config.yaml not found"),
        PermissionError("config.yaml not readable"),
        ValueError("invalid config"),
        RuntimeError("yaml parse error"),
    ],
)
def test_get_config_returns_503_on_any_load_failure(monkeypatch, exception):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""

    def _broken_get_app_config():
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        raise exception

    monkeypatch.setattr(gateway_deps, "get_app_config", _broken_get_app_config)

    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/probe")

    assert response.status_code == 503
    assert response.json() == {"detail": "Configuration not available"}
