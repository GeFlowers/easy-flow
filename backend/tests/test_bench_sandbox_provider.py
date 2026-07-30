"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_module(name: str, relative: str):
    """为“加载模块”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_module("bench_sandbox_provider", "scripts/benchmark/bench_sandbox_provider.py")
summarize = _load_module("summarize_bench", "scripts/benchmark/summarize_bench.py")


class _FakeProvider:
    """归集“该项提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
    def __init__(self, sandbox: Any | None = None) -> None:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self._lock = bench.threading.Lock()
        self._warm_pool: dict[str, tuple[Any, float]] = {}
        self._sandbox = sandbox or _FakeSandbox("ok")
        self.released: list[str] = []
        self.shutdown_called = False

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """为“获取”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return "sandbox-id"

    def get(self, sandbox_id: str):
        """为“获取”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return self._sandbox

    def release(self, sandbox_id: str) -> None:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self.released.append(sandbox_id)

    def shutdown(self) -> None:
        """为“关闭”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self.shutdown_called = True


class _FakeWarmReclaimProvider(_FakeProvider):
    """归集“该项预热回收提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """为“获取”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        reclaimed = self._reclaim_warm_pool("sandbox-id")
        assert reclaimed is not None
        return reclaimed

    def _reclaim_warm_pool(self, sandbox_id: str) -> str | None:
        """为“回收预热池”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        return sandbox_id


class _FakeSandbox:
    """归集“该项沙箱”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
    def __init__(self, output: str | Exception) -> None:
        """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        self.output = output

    def execute_command(self, command: str, timeout: float | None = None) -> str:
        """为“执行命令”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def test_aio_provider_default_leaves_image_unset(monkeypatch, tmp_path):
    """验证“异步输入输出提供方默认值该项镜像该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    captured_config: dict[str, Any] = {}

    def _factory(config: dict[str, Any]):
        """为“工厂”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        captured_config.update(config)
        return _FakeProvider(), {"replicas": config["replicas"], "idle_timeout": config["idle_timeout"], "image": config.get("image")}

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "aio-docker", _factory)

    rc = bench.main(
        [
            "--provider",
            "aio-docker",
            "--iterations",
            "0",
            "--warmup-iterations",
            "0",
            "--output",
            str(tmp_path / "out.jsonl"),
        ]
    )

    assert rc == 0
    assert captured_config["image"] is None


def test_explicit_aio_provider_image_is_forwarded(monkeypatch, tmp_path):
    """验证“显式异步输入输出提供方镜像该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    captured_config: dict[str, Any] = {}

    def _factory(config: dict[str, Any]):
        """为“工厂”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        captured_config.update(config)
        return _FakeProvider(), {"replicas": config["replicas"], "idle_timeout": config["idle_timeout"], "image": config.get("image")}

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "aio-docker", _factory)

    rc = bench.main(
        [
            "--provider",
            "aio-docker",
            "--image",
            "custom/aio:latest",
            "--iterations",
            "0",
            "--warmup-iterations",
            "0",
            "--output",
            str(tmp_path / "out.jsonl"),
        ]
    )

    assert rc == 0
    assert captured_config["image"] == "custom/aio:latest"


def test_failed_turn_releases_acquired_sandbox() -> None:
    """验证“失败轮次该项该项沙箱”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider = _FakeProvider(_FakeSandbox(RuntimeError("boom")))

    result = bench._run_one_turn(
        provider=provider,
        provider_name="fake",
        scenario="warm_same_thread",
        workload_name="noop",
        command="true",
        iteration=0,
        concurrency=1,
        user_id="user",
        thread_id="thread",
        no_warmpool=False,
    )

    assert result.success is False
    assert provider.released == ["sandbox-id"]


def test_error_string_output_records_failed_turn() -> None:
    """验证“错误字符串输出该项失败轮次”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider = _FakeProvider(_FakeSandbox("Error: vsock disconnected"))

    result = bench._run_one_turn(
        provider=provider,
        provider_name="fake",
        scenario="warm_same_thread",
        workload_name="noop",
        command="true",
        iteration=0,
        concurrency=1,
        user_id="user",
        thread_id="thread",
        no_warmpool=False,
    )

    assert result.success is False
    assert result.error == "Error: vsock disconnected"
    assert provider.released == ["sandbox-id"]


def test_warm_hit_uses_reclaim_instrumentation_not_pre_acquire_sample() -> None:
    """验证“预热该项使用回收该项该项该项获取该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    provider = _FakeWarmReclaimProvider(_FakeSandbox("ok"))
    bench._install_warm_hit_tracking(provider)

    result = bench._run_one_turn(
        provider=provider,
        provider_name="fake",
        scenario="warm_same_thread",
        workload_name="noop",
        command="true",
        iteration=0,
        concurrency=1,
        user_id="user",
        thread_id="thread",
        no_warmpool=False,
    )

    assert result.success is True
    assert result.warm_hit is True


def test_summary_preserves_all_failure_group() -> None:
    """验证“汇总保留全部失败该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    rows = [
        {
            "provider": "boxlite",
            "scenario": "warm_same_thread",
            "workload": "noop",
            "concurrency": 1,
            "success": False,
            "error": "RuntimeError('boom')",
            "acquire_ms": 0,
            "total_ms": 12.3,
        }
    ]

    summary = summarize._summarize(rows, ["provider", "scenario", "workload", "concurrency"])

    assert summary == [
        {
            "provider": "boxlite",
            "scenario": "warm_same_thread",
            "workload": "noop",
            "concurrency": 1,
            "count": 1,
            "ok": 0,
            "errors": 1,
            "warm_hit_rate": 0,
            "acquire_p50": 0.0,
            "acquire_p95": 0.0,
            "acquire_p99": 0.0,
            "acquire_mean": 0.0,
            "run_p50": 0.0,
            "run_p95": 0.0,
            "release_p50": 0.0,
            "total_p50": 0.0,
            "total_p95": 0.0,
            "total_p99": 0.0,
            "total_mean": 0.0,
        }
    ]


def test_health_check_skip_seconds_is_forwarded_and_serialized(monkeypatch, tmp_path):
    """验证“健康检查该项跳过该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    captured_config: dict[str, Any] = {}

    def _factory(config: dict[str, Any]):
        """为“工厂”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        captured_config.update(config)
        return _FakeProvider(), {
            "replicas": config["replicas"],
            "idle_timeout": config["idle_timeout"],
            "image": config.get("image"),
            "health_check_skip_seconds": config.get("health_check_skip_seconds"),
        }

    monkeypatch.setitem(bench.PROVIDER_FACTORIES, "boxlite", _factory)
    output_path = tmp_path / "out.jsonl"

    rc = bench.main(
        [
            "--provider",
            "boxlite",
            "--iterations",
            "1",
            "--warmup-iterations",
            "0",
            "--health-check-skip-seconds",
            "7.5",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert captured_config["health_check_skip_seconds"] == 7.5
    row = __import__("json").loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["health_check_skip_seconds"] == 7.5


def test_boxlite_factory_restores_module_state(monkeypatch):
    """验证“轻量隔离容器工厂该项模块状态”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    import deerflow.community.boxlite.provider as provider_mod

    original_get_app_config = provider_mod.get_app_config

    class _FactoryProvider:
        """归集“工厂提供方”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
        _create_box = object()

        def __init__(self) -> None:
            """为“该项”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
            self.created = True

    original_create_box = _FactoryProvider._create_box
    monkeypatch.setattr(provider_mod, "BoxliteProvider", _FactoryProvider)

    provider, _ = bench._make_boxlite_provider({})

    assert isinstance(provider, _FactoryProvider)
    assert provider_mod.get_app_config is original_get_app_config
    assert _FactoryProvider._create_box is original_create_box


def test_boxlite_shim_workaround_retries_after_fixing_permissions(monkeypatch, tmp_path):
    """验证“轻量隔离容器该项该项该项该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    boxes_dir = tmp_path / "boxes"
    shim = boxes_dir / "deadbeef" / "bin" / "boxlite-shim"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\n", encoding="utf-8")
    shim.chmod(0o644)

    calls = 0

    def _create_box(_sandbox_id: str):
        """为“创建隔离容器”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("shim not executable")
        return "ok"

    monkeypatch.setattr(bench, "_boxlite_version", lambda: "0.9.7")

    result = bench._create_box_with_097_shim_workaround(
        _create_box,
        "sandbox-id",
        boxes_dir=str(boxes_dir),
    )

    assert result == "ok"
    assert calls == 2
    assert shim.stat().st_mode & 0o111


def test_boxlite_shim_workaround_loud_fails_for_other_versions(monkeypatch, tmp_path):
    """验证“轻量隔离容器该项该项该项失败该项该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    boxes_dir = tmp_path / "boxes"
    monkeypatch.setattr(bench, "_boxlite_version", lambda: "0.9.8")

    def _create_box(_sandbox_id: str):
        """为“创建隔离容器”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
        raise RuntimeError("shim not executable")

    with __import__("pytest").raises(RuntimeError, match="only supports boxlite 0.9.7"):
        bench._create_box_with_097_shim_workaround(
            _create_box,
            "sandbox-id",
            boxes_dir=str(boxes_dir),
        )
