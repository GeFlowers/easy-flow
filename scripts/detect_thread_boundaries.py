#!/usr/bin/env python3
"""本脚本负责检测 会话。安全边界：仅处理显式指定的输入与路径，不作为常驻生产服务入口。"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from _detector_cli import run_detector


def main(argv: Sequence[str] | None = None) -> int:
    '未说明'
    return run_detector("support.detectors.thread_boundaries", argv)


if __name__ == "__main__":
    sys.exit(main())
