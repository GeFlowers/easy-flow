'定义 test_detector_repo_root 模块提供的职责与可复用接口。\n\nPin fail-loud repo-root resolution and the shared CLI shim for the detector tooling.\n\nThe failure mode being guarded: depth-indexed `parents[N]` resolution from a\nrelocated detector file silently resolves a wrong root, scans nothing, and\nreports zero findings. Resolution must instead raise when no repository\nmarker is found.\n'

from __future__ import annotations

from pathlib import Path

import pytest
from support.detectors import blocking_io_changed, blocking_io_static, thread_boundaries
from support.detectors.repo_root import resolve_repo_root

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_repo_root_finds_marker_from_detector_location():
    '验证 resolve、repo、root、finds、marker、from、detector、location 场景下的预期行为、边界条件与结果'
    resolved = resolve_repo_root(Path(blocking_io_static.__file__))
    assert resolved == REPO_ROOT
    assert (resolved / ".git").exists()


def test_all_detectors_share_the_resolved_root():
    '验证 all、detectors、share、the、resolved、root 场景下的预期行为、边界条件与结果'
    assert blocking_io_static.REPO_ROOT == REPO_ROOT
    assert blocking_io_changed.REPO_ROOT == REPO_ROOT
    assert thread_boundaries.REPO_ROOT == REPO_ROOT


def test_unmarked_location_raises_instead_of_scanning_nothing(tmp_path: Path):
    '验证 unmarked、location、raises、instead、of、scanning、nothing 场景下的预期行为、边界条件与结果'
    start = tmp_path / "moved" / "detectors" / "blocking_io_static.py"
    with pytest.raises(RuntimeError, match=r"\.git"):
        resolve_repo_root(start)


def test_cli_shims_delegate_to_their_detectors(capsys: pytest.CaptureFixture[str]):
    # conftest puts scripts/ on sys.path; --help proves the shim resolves and
    # conftest将scripts/放在sys.path上； --help 证明垫片解析并且
    '验证 cli、shims、delegate、to、their、detectors 场景下的预期行为、边界条件与结果'
    import detect_blocking_io_static
    import detect_thread_boundaries
    import scan_changed_blocking_io

    for shim, description_fragment in (
        (detect_blocking_io_static, "Statically inventory blocking IO calls"),
        (detect_thread_boundaries, "Detect async/thread boundary points"),
        (scan_changed_blocking_io, "blocking-IO candidates this change introduces"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            shim.main(["--help"])
        assert excinfo.value.code == 0
        assert description_fragment in capsys.readouterr().out
