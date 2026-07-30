'未说明'

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from uvicorn.config import resolve_reload_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]

LAUNCHERS = {
    "scripts/serve.sh": REPO_ROOT / "scripts" / "serve.sh",
    "docker/dev-entrypoint.sh": REPO_ROOT / "docker" / "dev-entrypoint.sh",
}

# Shell terminators / redirects that end a simple command's argument list.
_CMD_BOUNDARY = re.compile(r"[;&|<>]")


def _logical_lines(script: str) -> list[str]:
    '未说明'
    folded = script.replace("\\\n", " ")
    return [line for line in folded.splitlines() if not line.lstrip().startswith("#")]


def _shlex(fragment: str) -> list[str]:
    '未说明'
    try:
        return shlex.split(fragment, comments=True)
    except ValueError:
        return fragment.split()


# ``--reload-exclude`` followed by ``=`` or whitespace, then a value that is a
# single-quoted group, a double-quoted group, or a bare token. The quoted
# alternatives match a *balanced* pair first, so serve.sh's surrounding
# ``GATEWAY_EXTRA_FLAGS="..."`` closing quote is never swallowed into the value.
_RELOAD_EXCLUDE = re.compile(r"""--reload-exclude[=\s]+('[^']*'|"[^"]*"|[^\s'"]+)""")


def _reload_exclude_values(script: str) -> list[str]:
    '未说明'
    values: list[str] = []
    for line in _logical_lines(script):
        for raw in _RELOAD_EXCLUDE.findall(line):
            values.append(raw.strip("\"'"))
    return values


def _mkdir_dirs(script: str) -> set[str]:
    '未说明'
    dirs: set[str] = set()
    for line in _logical_lines(script):
        match = re.search(r"\bmkdir\b(.*)", line)
        if not match:
            continue
        args = _CMD_BOUNDARY.split(match.group(1), maxsplit=1)[0]
        for token in _shlex(args):
            if token.startswith("-"):  # skip flags such as -p
                continue
            dirs.add(token)
    return dirs


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="pathlib accepts absolute glob patterns on 3.13+, so the crash is 3.12-only",
)
def test_resolve_reload_patterns_crashes_on_missing_absolute_dir(tmp_path):
    '未说明'
    missing = tmp_path / "sandbox"  # absolute path that does not exist yet
    assert not missing.exists()
    with pytest.raises(NotImplementedError):
        resolve_reload_patterns([str(missing)], [])


def test_resolve_reload_patterns_is_safe_once_dir_exists(tmp_path):
    '未说明'
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    _patterns, directories = resolve_reload_patterns([str(sandbox)], [])
    resolved = {d.resolve() for d in directories}
    assert sandbox.resolve() in resolved


@pytest.mark.parametrize("name", list(LAUNCHERS))
def test_launcher_precreates_every_absolute_reload_exclude(name):
    '未说明'
    script = LAUNCHERS[name].read_text(encoding="utf-8")
    created = _mkdir_dirs(script)

    absolute_excludes = [v for v in _reload_exclude_values(script) if v.startswith(("/", "$"))]
    assert absolute_excludes, f"{name}: expected at least one absolute reload-exclude"

    for value in absolute_excludes:
        assert value in created, f"{name}: absolute reload-exclude {value!r} is never created via mkdir (created dirs: {sorted(created)})"


@pytest.mark.parametrize("name", list(LAUNCHERS))
def test_sandbox_mkdir_precedes_uvicorn_launch(name):
    '未说明'
    lines = LAUNCHERS[name].read_text(encoding="utf-8").splitlines()
    launch_idx = next((i for i, ln in enumerate(lines) if "uv run uvicorn" in ln), None)
    mkdir_idx = next((i for i, ln in enumerate(lines) if re.search(r"\bmkdir\b", ln) and "sandbox" in ln), None)

    assert launch_idx is not None, f"{name}: could not locate the 'uv run uvicorn' launch line"
    assert mkdir_idx is not None, f"{name}: could not locate the sandbox mkdir line"
    assert mkdir_idx < launch_idx, f"{name}: sandbox mkdir (line {mkdir_idx + 1}) must precede uvicorn launch (line {launch_idx + 1})"


def test_precreated_sandbox_artifacts_are_gitignored():
    '未说明'
    probe = "backend/sandbox/__artifact_probe__"
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", probe],
        capture_output=True,
    )
    if result.returncode == 128:  # not a git checkout (e.g. packaged install)
        pytest.skip("not inside a git working tree")
    assert result.returncode == 0, "backend/sandbox/* should be gitignored (see backend/.gitignore '/sandbox/')"
