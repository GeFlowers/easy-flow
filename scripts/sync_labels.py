#!/usr/bin/env python3
"""本脚本负责同步。安全边界：仅处理显式指定的输入与路径，不作为常驻生产服务入口。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - guidance for local runs
    sys.exit(
        "PyYAML is required. Run via:\n"
        "  uv run --with pyyaml python scripts/sync_labels.py"
    )

LABELS_FILE = Path(__file__).resolve().parent.parent / ".github" / "labels.yml"


def load_labels(path: Path) -> list[dict[str, str]]:
    """执行加载对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    labels = data.get("labels")
    if not isinstance(labels, list) or not labels:
        sys.exit(f"No labels found in {path}")
    for label in labels:
        if not isinstance(label, dict) or "name" not in label:
            sys.exit(f"Invalid label entry (missing 'name'): {label!r}")
    return labels


def sync_label(label: dict[str, str], repo: str | None, dry_run: bool) -> bool:
    """执行同步 标签对应的单一步骤；仅作用于调用方传入的范围，并将异常交由调用方处理。"""
    name = str(label["name"])
    color = str(label.get("color", "ededed")).lstrip("#")
    description = str(label.get("description", ""))

    cmd = ["gh", "label", "create", name, "--color", color, "--force"]
    if description:
        cmd += ["--description", description]
    if repo:
        cmd += ["--repo", repo]

    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return True

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ {name}: {result.stderr.strip()}", file=sys.stderr)
        return False
    print(f"  ✓ {name}")
    return True


def main() -> int:
    '未说明'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Target repository as OWNER/NAME")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the gh commands without executing them",
    )
    args = parser.parse_args()

    labels = load_labels(LABELS_FILE)
    target = args.repo or "(current repository)"
    print(f"Syncing {len(labels)} labels to {target}")

    failures = sum(
        0 if sync_label(label, args.repo, args.dry_run) else 1 for label in labels
    )

    if failures:
        print(f"\n{failures} label(s) failed to sync", file=sys.stderr)
        return 1
    print(f"\nDone — {len(labels)} labels in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
