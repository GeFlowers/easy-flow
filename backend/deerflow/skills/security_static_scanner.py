'''保留旧模块路径，并从原生技能扫描器重新导出兼容类型与函数。'''

from deerflow.skills.skillscan import (
    SecurityFinding as StaticFinding,
)
from deerflow.skills.skillscan import (
    StaticScanBlockedError,
    StaticScannerError,
    enforce_static_scan,
    format_static_findings,
    scan_archive_preflight,
    scan_skill_dir,
    skill_scan_enabled,
)

__all__ = [
    "StaticFinding",
    "StaticScanBlockedError",
    "StaticScannerError",
    "enforce_static_scan",
    "format_static_findings",
    "scan_archive_preflight",
    "scan_skill_dir",
    "skill_scan_enabled",
]
