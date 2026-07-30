"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import textwrap
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
pytest.importorskip("monocle_apptrace")

from deerflow.config import is_monocle_tracing_enabled
from deerflow.config.tracing_config import get_tracing_config, reset_tracing_config
from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled

_TRACING_ENV = (
    "MONOCLE_TRACING",
    "MONOCLE_EXPORTERS",
    "OKAHU_API_KEY",
    "LANGFUSE_TRACING",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


@pytest.fixture(autouse=True)
def clear_monocle_env(monkeypatch):
    """提供隔离的测试夹具：创建调用用例所需依赖，并保持既定资源回收边界。"""
    for name in _TRACING_ENV:
        monkeypatch.delenv(name, raising=False)
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    monkeypatch.setattr("deerflow.tracing.monocle._setup_completed", False)
    reset_tracing_config()
    yield
    reset_tracing_config()


def test_disabled_by_default():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    assert is_monocle_tracing_enabled() is False
    assert get_tracing_config().monocle.enabled is False


def test_setup_noop_when_disabled(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    called = False

    def _fail(*args, **kwargs):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        nonlocal called
        called = True

    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", _fail)
    assert setup_monocle_tracing_if_enabled() is False
    assert called is False


def test_toggles_on_and_sets_up(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    reset_tracing_config()

    captured: dict = {}
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: captured.update(kw))

    assert is_monocle_tracing_enabled() is True
    assert setup_monocle_tracing_if_enabled() is True
    assert captured == {"workflow_name": "deer-flow", "monocle_exporters_list": "file"}


def test_custom_exporters(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "file,console")
    reset_tracing_config()

    captured: dict = {}
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: captured.update(kw))

    assert setup_monocle_tracing_if_enabled() is True
    assert captured["monocle_exporters_list"] == "file,console"


def test_warns_on_non_file_exporter(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "file,s3")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    warnings = [r.message for r in caplog.records if "beyond the local" in r.message]
    assert warnings, "expected an off-box exporter warning"
    assert "s3" in warnings[0]
    assert "Langfuse" not in warnings[0]  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


def test_off_box_warning_mentions_langfuse_when_co_enabled(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "okahu")
    monkeypatch.setenv("OKAHU_API_KEY", "okh_test")
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    warnings = [r.message for r in caplog.records if "beyond the local" in r.message]
    assert warnings, "expected an off-box exporter warning"
    assert "Langfuse" in warnings[0]


def test_no_off_box_warning_for_file_exporter(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    assert not any("beyond the local" in r.message for r in caplog.records)


def test_no_off_box_warning_for_console_exporter(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "file,console")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    assert not any("beyond the local" in r.message for r in caplog.records)


def test_coexists_with_langfuse():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    script = textwrap.dedent(
        """
        import os
        os.environ["MONOCLE_TRACING"] = "true"
        os.environ["MONOCLE_EXPORTERS"] = "console"
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test"
        os.environ["LANGFUSE_HOST"] = "http://127.0.0.1:9"  # unreachable; offline test

        from opentelemetry import trace

        from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled

        # Gateway order: Monocle at startup, Langfuse per-run afterwards.
        assert setup_monocle_tracing_if_enabled() is True
        provider = trace.get_tracer_provider()

        from langfuse import Langfuse

        Langfuse(tracing_enabled=True)

        assert trace.get_tracer_provider() is provider  # provider not replaced
        # NOTE: reaches into OTel SDK internals (no public API lists a
        # provider's span processors). The SDK is pinned by uv.lock; if a bump
        # renames these attributes, update this introspection — the coexistence
        # behavior itself is unaffected.
        names = [type(p).__name__ for p in provider._active_span_processor._span_processors]
        assert any("Langfuse" in n for n in names), names  # Langfuse attached alongside Monocle
        print("COEXIST_OK")
        """
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "COEXIST_OK" in result.stdout


def test_rejects_unknown_exporter(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "fle")
    reset_tracing_config()
    with pytest.raises(ValueError, match="unknown exporter"):
        setup_monocle_tracing_if_enabled()


def test_okahu_exporter_requires_api_key(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "okahu")
    reset_tracing_config()
    with pytest.raises(ValueError, match="OKAHU_API_KEY"):
        setup_monocle_tracing_if_enabled()


def test_okahu_exporter_with_api_key_ok(monkeypatch):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "okahu")
    monkeypatch.setenv("OKAHU_API_KEY", "okh_test")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    assert setup_monocle_tracing_if_enabled() is True


def test_embedded_hint_when_enabled_but_uninitialized(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.tracing import build_tracing_callbacks

    monkeypatch.setenv("MONOCLE_TRACING", "true")
    reset_tracing_config()
    monkeypatch.setattr("deerflow.tracing.monocle._setup_completed", False)

    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
    with caplog.at_level(logging.DEBUG, logger="deerflow.tracing.factory"):
        assert build_tracing_callbacks() == []

    assert any("not initialized in this process" in r.message for r in caplog.records)


def test_no_embedded_hint_after_setup(monkeypatch, caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from deerflow.tracing import build_tracing_callbacks

    monkeypatch.setenv("MONOCLE_TRACING", "true")
    reset_tracing_config()
    monkeypatch.setattr("deerflow.tracing.monocle._setup_completed", False)
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)
    assert setup_monocle_tracing_if_enabled() is True

    with caplog.at_level(logging.DEBUG, logger="deerflow.tracing.factory"):
        build_tracing_callbacks()

    assert not any("not initialized in this process" in r.message for r in caplog.records)


def test_no_import_time_setup():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    script = textwrap.dedent(
        """
        from opentelemetry import trace
        from opentelemetry.trace import ProxyTracerProvider

        import deerflow.agents as agents

        assert not hasattr(agents, "setup_monocle_telemetry")
        # Still the SDK-less default proxy: no provider was installed on import.
        assert isinstance(trace.get_tracer_provider(), ProxyTracerProvider)
        print("IMPORT_CLEAN_OK")
        """
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "IMPORT_CLEAN_OK" in result.stdout


def test_double_invoke_is_idempotent():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    script = textwrap.dedent(
        """
        import os
        os.environ["MONOCLE_TRACING"] = "true"
        os.environ["MONOCLE_EXPORTERS"] = "console"  # avoid writing .monocle/ files
        from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled
        from monocle_apptrace.instrumentation.common.instrumentor import get_monocle_instrumentor

        assert setup_monocle_tracing_if_enabled() is True
        first = get_monocle_instrumentor()
        assert first is not None
        assert setup_monocle_tracing_if_enabled() is True
        assert get_monocle_instrumentor() is first  # no second provider installed
        print("IDEMPOTENT_OK")
        """
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "IDEMPOTENT_OK" in result.stdout


def test_gateway_lifespan_initializes_monocle():
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from fastapi import FastAPI

    from app.gateway.app import lifespan

    @asynccontextmanager
    async def _noop_langgraph_runtime(_app, _startup_config):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        yield

    startup_config = SimpleNamespace(log_level="INFO", memory=SimpleNamespace(token_counting="char"))
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})

    async def fake_start(_startup_config):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return fake_service

    setup_spy = MagicMock(return_value=False)

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.setup_monocle_tracing_if_enabled", setup_spy),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
    ):

        async def drive() -> None:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            async with lifespan(FastAPI()):
                pass

        asyncio.run(drive())

    setup_spy.assert_called_once_with()


def test_gateway_lifespan_survives_monocle_setup_failure(caplog):
    """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
    from fastapi import FastAPI

    from app.gateway.app import lifespan

    @asynccontextmanager
    async def _noop_langgraph_runtime(_app, _startup_config):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        yield

    startup_config = SimpleNamespace(log_level="INFO", memory=SimpleNamespace(token_counting="char"))
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})

    async def fake_start(_startup_config):
        """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
        return fake_service

    setup_spy = MagicMock(side_effect=ValueError("MONOCLE_EXPORTERS has unknown exporter(s): fle."))

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.setup_monocle_tracing_if_enabled", setup_spy),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
    ):

        async def drive() -> None:
            """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
            async with lifespan(FastAPI()):
                pass

        with caplog.at_level(logging.ERROR, logger="app.gateway.app"):
            asyncio.run(drive())  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    setup_spy.assert_called_once_with()
    assert any("Monocle tracing setup failed" in r.message for r in caplog.records)
