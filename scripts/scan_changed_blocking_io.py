#!/usr/bin/env python3
"""扫描 Git 变更文件中可能存在的阻塞 I/O 调用。"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from _detector_cli import run_detector


def main(argv: Sequence[str] | None = None) -> int:
    """调用变更文件阻塞 I/O 扫描器并透传命令行参数。"""
    return run_detector("support.detectors.blocking_io_changed", argv)


if __name__ == "__main__":
    sys.exit(main())
