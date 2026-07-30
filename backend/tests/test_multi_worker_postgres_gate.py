"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.gateway.deps import _enforce_postgres_for_multi_worker, langgraph_runtime
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.run_ownership_config import RunOwnershipConfig


def _config_with_backend(backend: str, *, heartbeat_enabled: bool | None = None) -> SimpleNamespace:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    run_ownership = RunOwnershipConfig(heartbeat_enabled=heartbeat_enabled) if heartbeat_enabled is not None else None
    return SimpleNamespace(database=DatabaseConfig(backend=backend), run_ownership=run_ownership)


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_gate_noop_when_gateway_workers_unset(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


def test_gate_noop_for_single_worker(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


def test_gate_allows_multi_worker_with_postgres_and_heartbeat(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=True))


def test_gate_rejects_multi_worker_with_sqlite(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=2" in msg
    assert "postgres" in msg.lower()
    assert "sqlite" in msg.lower()


def test_gate_rejects_multi_worker_with_memory(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit):
        _enforce_postgres_for_multi_worker(_config_with_backend("memory"))


def test_gate_rejects_high_worker_counts(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "4")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    assert "GATEWAY_WORKERS=4" in str(exc_info.value)


def test_gate_treats_invalid_env_as_single_worker(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    for invalid in ("", "auto", "1.5", "abc", "0x4"):
        monkeypatch.setenv("GATEWAY_WORKERS", invalid)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_treats_zero_and_negatives_as_single_worker(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    for value in ("0", "-1", "-999"):
        monkeypatch.setenv("GATEWAY_WORKERS", value)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_error_message_lists_both_remediations(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=1" in msg, "must mention the rollback knob"
    assert "Postgres" in msg, "must mention the alternative backend"


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


def test_gate_rejects_multi_worker_without_heartbeat(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=False))
    msg = str(exc_info.value)
    assert "heartbeat_enabled=true" in msg


def test_gate_rejects_multi_worker_without_run_ownership_config(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=None))
    msg = str(exc_info.value)
    assert "heartbeat_enabled=true" in msg


def test_gate_heartbeat_check_not_triggered_for_single_worker(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=False))


def test_gate_heartbeat_check_not_triggered_for_sqlite(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", heartbeat_enabled=True))
    msg = str(exc_info.value)
    assert "postgres" in msg.lower()


# ---------------------------------------------------------------------------
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_langgraph_runtime_invokes_gate_before_persistence_setup(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")

    init_engine_from_config = AsyncMock(name="init_engine_from_config")

    @asynccontextmanager
    async def _noop_stream_bridge(_config):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        yield MagicMock()

    with (
        patch(
            "deerflow.persistence.engine.init_engine_from_config",
            init_engine_from_config,
        ),
        patch("deerflow.runtime.make_stream_bridge", side_effect=_noop_stream_bridge) as make_stream_bridge,
        patch("deerflow.runtime.make_store", side_effect=_noop_stream_bridge) as make_store,
    ):
        app = FastAPI()
        startup_config = _config_with_backend("sqlite")
        with pytest.raises(SystemExit):
            async with langgraph_runtime(app, startup_config):
                pass

    init_engine_from_config.assert_not_called()
    make_stream_bridge.assert_not_called()
    make_store.assert_not_called()
