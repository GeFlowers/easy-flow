"定义 test_dev_entrypoint 模块提供的职责与可复用接口。\n\nUnit tests for docker/dev-entrypoint.sh (UV_EXTRAS validation + parsing).\n\nExercises the script via its `--print-extras` dry-run hook so we don't actually\nlaunch uvicorn or hit /app/logs. Together with test_detect_uv_extras.py these\ncover both the local make-dev path and the docker-compose-dev path with the\nsame shape — see PR #2767 / Issue #2754.\n"

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "dev-entrypoint.sh"


def _run(uv_extras: str | None) -> subprocess.CompletedProcess[str]:
    '执行 _run 的明确职责，并返回与调用约定一致的结果。\n\nInvoke `dev-entrypoint.sh --print-extras` with UV_EXTRAS set.'
    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    if uv_extras is not None:
        env["UV_EXTRAS"] = uv_extras
    return subprocess.run(
        ["sh", str(ENTRYPOINT), "--print-extras"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_entrypoint_script_exists_and_is_posix_sh():
    '验证 entrypoint、script、exists、and、is、posix、sh 场景下的预期行为、边界条件与结果'
    assert ENTRYPOINT.is_file()
    # 在运行前捕获语法错误 - `sh -n` 是仅解析检查。
    proc = subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_entrypoint_excludes_runtime_state_from_uvicorn_reload():
    '验证 entrypoint、excludes、runtime、state、from、uvicorn、reload 场景下的预期行为、边界条件与结果'
    content = ENTRYPOINT.read_text(encoding="utf-8")

    assert ': "${DEER_FLOW_HOME:=/app/backend/.deer-flow}"' in content
    # 沙箱也必须创建，而不仅仅是 .deer-flow (#3459 / #3454)。
    assert 'mkdir -p "$DEER_FLOW_HOME" /app/backend/.deer-flow /app/backend/sandbox' in content
    assert "--reload-include='*.yaml .env'" not in content
    assert "--reload-include='*.yaml'" in content
    assert "--reload-include='.env'" in content
    assert "--reload-exclude=/app/backend/sandbox" in content
    assert '--reload-exclude="$DEER_FLOW_HOME"' in content
    assert "--reload-exclude=/app/backend/.deer-flow" in content


def test_no_uv_extras_yields_empty_flags():
    '验证 no、uv、extras、yields、empty、flags 场景下的预期行为、边界条件与结果'
    proc = _run(None)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_single_extra():
    '验证 single、extra 场景下的预期行为、边界条件与结果'
    proc = _run("postgres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres"


def test_multi_extra_comma_separated():
    '验证 multi、extra、comma、separated 场景下的预期行为、边界条件与结果'
    proc = _run("postgres,ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_whitespace_separated():
    '验证 multi、extra、whitespace、separated 场景下的预期行为、边界条件与结果'
    proc = _run("postgres ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_mixed_separators():
    '验证 multi、extra、mixed、separators 场景下的预期行为、边界条件与结果'
    proc = _run(" postgres ,  ollama ,")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_empty_string_yields_empty_flags():
    '验证 empty、string、yields、empty、flags 场景下的预期行为、边界条件与结果'
    proc = _run("")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@pytest.mark.parametrize(
    "bad_value",
    [
        "; rm -rf /",  # the canonical injection attempt
        "$(whoami)",  # command substitution
        "`echo bad`",  # backticks
        "postgres;evil",  # mixed legal+illegal in a single token
        "1postgres",  # leading digit
        "-postgres",  # leading hyphen
        "post gres extra/path",  # contains slash
    ],
)
def test_metacharacters_abort_with_nonzero_exit(bad_value):
    '验证 metacharacters、abort、with、nonzero、exit 场景下的预期行为、边界条件与结果'
    proc = _run(bad_value)
    assert proc.returncode != 0, f"expected abort for {bad_value!r}, got 0"
    assert "is invalid" in proc.stderr
    assert proc.stdout.strip() == ""


def test_underscores_and_hyphens_in_name_are_allowed():
    "验证 underscores、and、hyphens、in、name、are、allowed 场景下的预期行为、边界条件与结果。\n\nMirrors uv's accepted shape for `[project.optional-dependencies]` keys."
    proc = _run("post_gres,post-gres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra post_gres --extra post-gres"
