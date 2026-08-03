#!/usr/bin/env python3
"""检查后端代码是否遵守线程边界调用约束。"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from _detector_cli import run_detector


def main(argv: Sequence[str] | None = None) -> int:
    """调用线程边界检测器并透传命令行参数。"""
    return run_detector("support.detectors.thread_boundaries", argv)


if __name__ == "__main__":
    sys.exit(main())
