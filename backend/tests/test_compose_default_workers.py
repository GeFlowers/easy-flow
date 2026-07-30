'定义 test_compose_default_workers 模块提供的职责与可复用接口。\n\nRegression test for the Docker Compose default Gateway worker count.\n\nThe Gateway holds run state (RunManager and the stream bridge) in process, so\nthe default deployment must run a single Uvicorn worker. Running more than one\nworker without a shared cross-worker stream bridge breaks run cancellation, SSE\nreconnects, request de-duplication, and IM channels (nginx has no sticky\nsessions, so requests scatter across workers that each keep their own run\nstate). This test pins the safe default so it cannot silently regress to a\nmulti-worker default, while still allowing operators to override it once a\nshared stream bridge exists.\n'

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yaml"


def _gateway_command() -> str:
    '执行 _gateway_command 的明确职责，并返回与调用约定一致的结果。\n\nReturn the gateway service command as a single string.'
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    command = compose["services"]["gateway"]["command"]
    # ``command`` 可能会加载为标量字符串或列表，具体取决于 YAML 样式。
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    return command


def test_gateway_defaults_to_single_worker():
    '验证 gateway、defaults、to、single、worker 场景下的预期行为、边界条件与结果。\n\nWith GATEWAY_WORKERS unset, the worker count must default to 1.'
    command = _gateway_command()
    match = re.search(r"GATEWAY_WORKERS:-(\d+)", command)
    assert match is not None, f"gateway command must set a GATEWAY_WORKERS default; got: {command}"
    assert match.group(1) == "1", f"default Gateway worker count must be 1, got {match.group(1)}"


def test_gateway_worker_count_remains_overridable():
    '验证 gateway、worker、count、remains、overridable 场景下的预期行为、边界条件与结果。\n\nThe worker count must stay configurable, not hard-coded to 1.'
    command = _gateway_command()
    assert "${GATEWAY_WORKERS:-1}" in command, f"worker count must use ${{GATEWAY_WORKERS:-1}} so operators can override it; got: {command}"
