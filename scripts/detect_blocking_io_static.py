#!/usr/bin/env python3
"""扫描后端代码中可能阻塞异步事件循环的调用。"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from _detector_cli import run_detector


def main(argv: Sequence[str] | None = None) -> int:
    """调用静态阻塞 I/O 检测器并透传命令行参数。"""
    return run_detector("support.detectors.blocking_io_static", argv)


if __name__ == "__main__":
    sys.exit(main())
