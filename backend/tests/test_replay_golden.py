"""本模块覆盖回放 基准结果的行为、边界与回归场景，确保既有契约稳定。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from _replay_fixture import REPLAY_MODEL_BLOCK, build_config_yaml, drive_gateway, prepare_hermetic_extras

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "replay"


def _reset_process_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """准备可控测试资源与状态，供后续断言读取。"""
    from deerflow.config import app_config as app_config_module
    from deerflow.config import paths as paths_module
    from deerflow.persistence import engine as engine_module

    for module, attr in (
        (app_config_module, "_app_config"),
        (app_config_module, "_app_config_path"),
        (app_config_module, "_app_config_mtime"),
        (paths_module, "_paths_singleton"),
        (engine_module, "_engine"),
        (engine_module, "_session_factory"),
    ):
        monkeypatch.setattr(module, attr, None, raising=False)


@pytest.mark.no_auto_user
def test_replay_write_read_file_ultra_matches_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """验证回放 写入 读取 文件 基准结果在预期条件及边界场景下的可观察行为，防止相关回归。"""
    scenario, mode = "write_read_file", "ultra"
    fixture_path = FIXTURE_DIR / f"{scenario}.{mode}.json"
    events_path = FIXTURE_DIR / f"{scenario}.{mode}.events.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setenv("DEERFLOW_REPLAY_FIXTURE", str(fixture_path))

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(build_config_yaml(model_block=REPLAY_MODEL_BLOCK, home=home), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(prepare_hermetic_extras(home)))

    _reset_process_singletons(monkeypatch)
    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(home / "db")

    # Fail loud on a replay miss. The gateway swallows a hash-miss into a normal
    # assistant error message, so the SSE *shapes* below stay green on a stale
    # fixture — the miss list is the only reliable signal at this layer.
    import replay_provider

    from app.gateway.app import create_app

    replay_provider.reset_replay_misses()

    events = drive_gateway(create_app(), prompt=fixture["prompt"], context=fixture["context"])

    assert events, "replay produced no SSE events"
    assert events[0]["event"] == "metadata", f"first event should be metadata, got {events[0]!r}"
    assert events[-1]["event"] == "end", f"last event should be end (run completed), got {events[-1]!r}"

    misses = replay_provider.replay_misses()
    assert not misses, f"replay miss ({len(misses)}): the fixture is stale vs the current system prompt or agent graph. Re-record it (see backend/docs/REPLAY_E2E.md). Missed hashes: {misses}"

    # Regenerate the committed golden after re-recording the fixture:
    #   DEERFLOW_WRITE_GOLDEN=1 uv run pytest tests/test_replay_golden.py
    if os.environ.get("DEERFLOW_WRITE_GOLDEN"):
        events_path.write_text(json.dumps({"scenario": scenario, "mode": mode, "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    golden = json.loads(events_path.read_text(encoding="utf-8"))["events"]
    # Guards backend SSE protocol drift: the event name + payload-key sequence
    # must match the committed golden. (Replay divergence is caught by the miss
    # assertion above, not here — a swallowed miss keeps the shapes identical.)
    assert events == golden, f"SSE event-shape sequence drifted from the golden.\ngot  ({len(events)}): {[e['event'] for e in events]}\nwant ({len(golden)}): {[e['event'] for e in golden]}"
