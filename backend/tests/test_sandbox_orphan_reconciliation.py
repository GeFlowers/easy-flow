'未说明'

import importlib
import json
import signal
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

# ── SandboxBackend.list_running() default ────────────────────────────────────


def test_backend_list_running_default_returns_empty():
    '未说明'
    from deerflow.community.aio_sandbox.backend import SandboxBackend

    class StubBackend(SandboxBackend):
        '未说明'
        def create(self, thread_id, sandbox_id, extra_mounts=None, *, user_id=None):
            """处理创建相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
            del thread_id, sandbox_id, extra_mounts, user_id
            pass

        def destroy(self, info):
            '未说明'
            pass

        def is_alive(self, info):
            '未说明'
            return False

        def discover(self, sandbox_id):
            '未说明'
            return None

    backend = StubBackend()
    assert backend.list_running() == []


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_local_backend():
    '未说明'
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

    return LocalContainerBackend(
        image="test-image:latest",
        base_port=8080,
        container_prefix="deer-flow-sandbox",
        config_mounts=[],
        environment={},
    )


def _make_inspect_entry(name: str, created: str, host_port: str | None = None) -> dict:
    '未说明'
    ports: dict = {}
    if host_port is not None:
        ports["8080/tcp"] = [{"HostIp": "0.0.0.0", "HostPort": host_port}]
    return {
        "Name": f"/{name}",  # docker inspect prefixes names with "/"
        "Created": created,
        "NetworkSettings": {"Ports": ports},
    }


def _mock_ps_and_inspect(monkeypatch, ps_output: str, inspect_payload: list | None):
    '未说明'
    import subprocess

    def mock_run(cmd, **kwargs):
        """处理模拟 运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        result = MagicMock()
        if len(cmd) >= 2 and cmd[1] == "ps":
            result.returncode = 0
            result.stdout = ps_output
            result.stderr = ""
            return result
        if len(cmd) >= 2 and cmd[1] == "inspect":
            if inspect_payload is None:
                result.returncode = 1
                result.stdout = ""
                result.stderr = "inspect failed"
                return result
            result.returncode = 0
            result.stdout = json.dumps(inspect_payload)
            result.stderr = ""
            return result
        result.returncode = 1
        result.stdout = ""
        result.stderr = "unexpected command"
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)


# ── LocalContainerBackend.list_running() ─────────────────────────────────────


def test_list_running_returns_containers(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\ndeer-flow-sandbox-def67890\n",
        inspect_payload=[
            _make_inspect_entry("deer-flow-sandbox-abc12345", "2026-04-08T01:22:50.000000000Z", "8081"),
            _make_inspect_entry("deer-flow-sandbox-def67890", "2026-04-08T02:22:50.000000000Z", "8082"),
        ],
    )

    infos = backend.list_running()

    assert len(infos) == 2
    ids = {info.sandbox_id for info in infos}
    assert ids == {"abc12345", "def67890"}
    urls = {info.sandbox_url for info in infos}
    assert "http://localhost:8081" in urls
    assert "http://localhost:8082" in urls


def test_list_running_empty_when_no_containers(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")
    _mock_ps_and_inspect(monkeypatch, ps_output="", inspect_payload=[])

    assert backend.list_running() == []


def test_list_running_skips_non_matching_names(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\nsome-other-container\n",
        inspect_payload=[
            _make_inspect_entry("deer-flow-sandbox-abc12345", "2026-04-08T01:22:50Z", "8081"),
        ],
    )

    infos = backend.list_running()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc12345"


def test_list_running_includes_containers_without_port(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\n",
        inspect_payload=[
            _make_inspect_entry("deer-flow-sandbox-abc12345", "2026-04-08T01:22:50Z", host_port=None),
        ],
    )

    infos = backend.list_running()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc12345"
    assert infos[0].sandbox_url == ""


def test_list_running_handles_docker_failure(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        """处理模拟 运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "daemon not running"
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend.list_running() == []


def test_list_running_handles_inspect_failure(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\n",
        inspect_payload=None,  # Signals inspect failure
    )

    assert backend.list_running() == []


def test_list_running_handles_malformed_inspect_json(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        """处理模拟 运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        result = MagicMock()
        if len(cmd) >= 2 and cmd[1] == "ps":
            result.returncode = 0
            result.stdout = "deer-flow-sandbox-abc12345\n"
            result.stderr = ""
        else:
            result.returncode = 0
            result.stdout = "this is not json"
            result.stderr = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend.list_running() == []


def test_list_running_uses_single_batch_inspect_call(monkeypatch):
    '未说明'
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    inspect_call_count = {"count": 0}

    import subprocess

    def mock_run(cmd, **kwargs):
        """处理模拟 运行相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        result = MagicMock()
        if len(cmd) >= 2 and cmd[1] == "ps":
            result.returncode = 0
            result.stdout = "deer-flow-sandbox-a\ndeer-flow-sandbox-b\ndeer-flow-sandbox-c\n"
            result.stderr = ""
            return result
        if len(cmd) >= 2 and cmd[1] == "inspect":
            inspect_call_count["count"] += 1
            # Expect all three names passed in a single call
            assert cmd[2:] == ["deer-flow-sandbox-a", "deer-flow-sandbox-b", "deer-flow-sandbox-c"]
            result.returncode = 0
            result.stdout = json.dumps(
                [
                    _make_inspect_entry("deer-flow-sandbox-a", "2026-04-08T01:22:50Z", "8081"),
                    _make_inspect_entry("deer-flow-sandbox-b", "2026-04-08T01:22:50Z", "8082"),
                    _make_inspect_entry("deer-flow-sandbox-c", "2026-04-08T01:22:50Z", "8083"),
                ]
            )
            result.stderr = ""
            return result
        result.returncode = 1
        result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    infos = backend.list_running()
    assert len(infos) == 3
    assert inspect_call_count["count"] == 1  # ← The core performance assertion


# ── _parse_docker_timestamp() ────────────────────────────────────────────────


def test_parse_docker_timestamp_with_nanoseconds():
    '未说明'
    from deerflow.community.aio_sandbox.local_backend import _parse_docker_timestamp

    ts = _parse_docker_timestamp("2026-04-08T01:22:50.123456789Z")
    assert ts > 0
    expected = datetime(2026, 4, 8, 1, 22, 50, tzinfo=UTC).timestamp()
    assert abs(ts - expected) < 1.0


def test_parse_docker_timestamp_without_fractional_seconds():
    '未说明'
    from deerflow.community.aio_sandbox.local_backend import _parse_docker_timestamp

    ts = _parse_docker_timestamp("2026-04-08T01:22:50Z")
    expected = datetime(2026, 4, 8, 1, 22, 50, tzinfo=UTC).timestamp()
    assert abs(ts - expected) < 1.0


def test_parse_docker_timestamp_empty_returns_zero():
    '未说明'
    from deerflow.community.aio_sandbox.local_backend import _parse_docker_timestamp

    assert _parse_docker_timestamp("") == 0.0
    assert _parse_docker_timestamp("not a timestamp") == 0.0


# ── _extract_host_port() ─────────────────────────────────────────────────────


def test_extract_host_port_returns_mapped_port():
    '未说明'
    from deerflow.community.aio_sandbox.local_backend import _extract_host_port

    entry = {"NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8081"}]}}}
    assert _extract_host_port(entry, 8080) == 8081


def test_extract_host_port_returns_none_when_unmapped():
    '未说明'
    from deerflow.community.aio_sandbox.local_backend import _extract_host_port

    entry = {"NetworkSettings": {"Ports": {}}}
    assert _extract_host_port(entry, 8080) is None


def test_extract_host_port_handles_missing_fields():
    '未说明'
    from deerflow.community.aio_sandbox.local_backend import _extract_host_port

    assert _extract_host_port({}, 8080) is None
    assert _extract_host_port({"NetworkSettings": None}, 8080) is None


# ── AioSandboxProvider._reconcile_orphans() ──────────────────────────────────


def _make_provider_for_reconciliation():
    '未说明'
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._shutdown_called = False
    provider._idle_checker_stop = threading.Event()
    provider._idle_checker_thread = None
    provider._config = {
        "idle_timeout": 600,
        "replicas": 3,
    }
    provider._backend = MagicMock()
    return provider


def test_reconcile_adopts_old_containers_into_warm_pool():
    '未说明'
    provider = _make_provider_for_reconciliation()
    now = time.time()

    old_info = SandboxInfo(
        sandbox_id="old12345",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-old12345",
        created_at=now - 1200,  # 20 minutes old, > 600s idle_timeout
    )
    provider._backend.list_running.return_value = [old_info]

    provider._reconcile_orphans()

    # Should NOT destroy directly — let idle checker handle it
    provider._backend.destroy.assert_not_called()
    assert "old12345" in provider._warm_pool


def test_reconcile_adopts_young_containers():
    '未说明'
    provider = _make_provider_for_reconciliation()
    now = time.time()

    young_info = SandboxInfo(
        sandbox_id="young123",
        sandbox_url="http://localhost:8082",
        container_name="deer-flow-sandbox-young123",
        created_at=now - 60,  # 1 minute old, < 600s idle_timeout
    )
    provider._backend.list_running.return_value = [young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "young123" in provider._warm_pool
    adopted_info, release_ts = provider._warm_pool["young123"]
    assert adopted_info.sandbox_id == "young123"


def test_reconcile_mixed_containers_all_adopted():
    '未说明'
    provider = _make_provider_for_reconciliation()
    now = time.time()

    old_info = SandboxInfo(
        sandbox_id="old_one",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-old_one",
        created_at=now - 1200,
    )
    young_info = SandboxInfo(
        sandbox_id="young_one",
        sandbox_url="http://localhost:8082",
        container_name="deer-flow-sandbox-young_one",
        created_at=now - 60,
    )
    provider._backend.list_running.return_value = [old_info, young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "old_one" in provider._warm_pool
    assert "young_one" in provider._warm_pool


def test_reconcile_skips_already_tracked_containers():
    '未说明'
    provider = _make_provider_for_reconciliation()
    now = time.time()

    existing_info = SandboxInfo(
        sandbox_id="existing1",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-existing1",
        created_at=now - 1200,
    )
    # Pre-populate _sandboxes to simulate already-tracked container
    provider._sandboxes["existing1"] = MagicMock()
    provider._backend.list_running.return_value = [existing_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    # The pre-populated sandbox should NOT be moved into warm pool
    assert "existing1" not in provider._warm_pool


def test_reconcile_handles_backend_failure():
    '未说明'
    provider = _make_provider_for_reconciliation()
    provider._backend.list_running.side_effect = RuntimeError("docker not available")

    # Should not raise
    provider._reconcile_orphans()

    assert provider._warm_pool == {}


def test_reconcile_no_running_containers():
    '未说明'
    provider = _make_provider_for_reconciliation()
    provider._backend.list_running.return_value = []

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert provider._warm_pool == {}


def test_reconcile_multiple_containers_all_adopted():
    '未说明'
    provider = _make_provider_for_reconciliation()
    now = time.time()

    info1 = SandboxInfo(sandbox_id="cont_one", sandbox_url="http://localhost:8081", created_at=now - 1200)
    info2 = SandboxInfo(sandbox_id="cont_two", sandbox_url="http://localhost:8082", created_at=now - 1200)

    provider._backend.list_running.return_value = [info1, info2]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "cont_one" in provider._warm_pool
    assert "cont_two" in provider._warm_pool


def test_reconcile_zero_created_at_adopted():
    '未说明'
    provider = _make_provider_for_reconciliation()

    info = SandboxInfo(sandbox_id="unknown1", sandbox_url="http://localhost:8081", created_at=0.0)
    provider._backend.list_running.return_value = [info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "unknown1" in provider._warm_pool


def test_reconcile_idle_timeout_zero_adopts_all():
    '未说明'
    provider = _make_provider_for_reconciliation()
    provider._config["idle_timeout"] = 0
    now = time.time()

    old_info = SandboxInfo(sandbox_id="old_one", sandbox_url="http://localhost:8081", created_at=now - 7200)
    young_info = SandboxInfo(sandbox_id="young_one", sandbox_url="http://localhost:8082", created_at=now - 60)
    provider._backend.list_running.return_value = [old_info, young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "old_one" in provider._warm_pool
    assert "young_one" in provider._warm_pool


# ── SIGHUP signal handler ───────────────────────────────────────────────────


def test_sighup_handler_registered():
    '未说明'
    if not hasattr(signal, "SIGHUP"):
        pytest.skip("SIGHUP not available on this platform")

    provider = _make_provider_for_reconciliation()

    # Save original handlers for ALL signals we'll modify
    original_sighup = signal.getsignal(signal.SIGHUP)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    original_sigint = signal.getsignal(signal.SIGINT)
    try:
        aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
        provider._original_sighup = original_sighup
        provider._original_sigterm = original_sigterm
        provider._original_sigint = original_sigint
        provider.shutdown = MagicMock()

        aio_mod.AioSandboxProvider._register_signal_handlers(provider)

        # Verify SIGHUP handler is no longer the default
        handler = signal.getsignal(signal.SIGHUP)
        assert handler != signal.SIG_DFL, "SIGHUP handler should be registered"
    finally:
        # Restore ALL original handlers to avoid leaking state across tests
        signal.signal(signal.SIGHUP, original_sighup)
        signal.signal(signal.SIGTERM, original_sigterm)
        signal.signal(signal.SIGINT, original_sigint)
