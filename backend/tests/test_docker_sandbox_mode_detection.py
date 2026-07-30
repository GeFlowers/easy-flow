'定义 test_docker_sandbox_mode_detection 模块提供的职责与可复用接口。\n\nRegression tests for docker sandbox mode detection logic.'

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "docker.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for docker.sh detection tests")


def _detect_mode_with_config(config_content: str) -> str:
    '执行 _detect_mode_with_config 的明确职责，并返回与调用约定一致的结果。\n\nWrite config content into a temp project root and execute detect_sandbox_mode.'
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        (tmp_root / "config.yaml").write_text(config_content, encoding="utf-8")

        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmp_root}' && detect_sandbox_mode"

        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

        return output


def test_detect_mode_defaults_to_local_when_config_missing():
    '验证 detect、mode、defaults、to、local、when、config、missing 场景下的预期行为、边界条件与结果。\n\nNo config file should default to local mode.'
    with tempfile.TemporaryDirectory() as tmpdir:
        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmpdir}' && detect_sandbox_mode"
        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

    assert output == "local"


def test_detect_mode_local_provider():
    '验证 detect、mode、local、provider 场景下的预期行为、边界条件与结果。\n\nLocal sandbox provider should map to local mode.'
    config = """
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"


def test_detect_mode_aio_without_provisioner_url():
    '验证 detect、mode、aio、without、provisioner、url 场景下的预期行为、边界条件与结果。\n\nAIO sandbox without provisioner_url should map to aio mode.'
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_provisioner_with_url():
    '验证 detect、mode、provisioner、with、url 场景下的预期行为、边界条件与结果。\n\nAIO sandbox with provisioner_url should map to provisioner mode.'
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "provisioner"


def test_detect_mode_ignores_commented_provisioner_url():
    '验证 detect、mode、ignores、commented、provisioner、url 场景下的预期行为、边界条件与结果。\n\nCommented provisioner_url should not activate provisioner mode.'
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  # provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_unknown_provider_falls_back_to_local():
    '验证 detect、mode、unknown、provider、falls、back、to、local 场景下的预期行为、边界条件与结果。\n\nUnknown sandbox provider should default to local mode.'
    config = """
sandbox:
  use: custom.module:UnknownProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"
