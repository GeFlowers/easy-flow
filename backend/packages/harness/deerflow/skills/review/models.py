'''定义技能包审查所用的版本标识、严重级别、资源限制和统一发现结构。'''

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

PACKAGE_SNAPSHOT_SCHEMA_VERSION = "deerflow.skill-package-snapshot.v1"
FACTS_SCHEMA_VERSION = "deerflow.skill-review.facts.v1"
REPORT_SCHEMA_VERSION = "deerflow.skill-review.report.v1"

Severity = Literal["blocker", "error", "warning", "info"]
ProfileName = Literal["deerflow", "agentskills"]

SEVERITY_RANK: dict[str, int] = {
    "blocker": 0,
    "error": 1,
    "warning": 2,
    "info": 3,
}

SKILLSCAN_SEVERITY_MAP: dict[str, Severity] = {
    "CRITICAL": "blocker",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "info",
}


@dataclass(frozen=True)
class PackageLimits:
    '''限制单个包允许的文件数量、单文件大小及累计内容大小。'''

    max_files: int = 4096
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024

    def to_dict(self) -> dict[str, int]:
        '''以字段名为键返回资源限制，供快照记录和序列化使用。'''
        return {
            "max_files": self.max_files,
            "max_file_bytes": self.max_file_bytes,
            "max_total_bytes": self.max_total_bytes,
        }


DEFAULT_PACKAGE_LIMITS = PackageLimits()


def stable_json_dumps(data: Any) -> str:
    '''生成键排序且无多余空格的 JSON 文本，保证报告序列化稳定。'''
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_relative_path(path: str) -> str:
    '''规范包内相对路径并拒绝空路径、绝对路径和目录向上跳转。'''
    raw = path.replace("\\", "/").strip()
    if not raw:
        raise ValueError("path must not be empty")
    pure = PurePosixPath(raw)
    if pure.is_absolute():
        raise ValueError("absolute paths are not allowed")
    normalized = posixpath.normpath(raw)
    if normalized in {"", "."}:
        raise ValueError("path must not resolve to package root")
    parts = PurePosixPath(normalized).parts
    if any(part in {"..", ""} for part in parts):
        raise ValueError("path must not contain parent-directory traversal")
    return normalized


def make_finding(
    rule_id: str,
    *,
    severity: Severity,
    message: str,
    remediation: str,
    source: str = "review-core",
    profile: str = "deerflow",
    path: str | None = None,
    line: int | None = None,
    evidence: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    '''按统一字段构造审查发现，并合并调用方提供的扩展字段。'''
    finding = {
        "rule_id": rule_id,
        "source": source,
        "profile": profile,
        "severity": severity,
        "path": path,
        "line": line,
        "message": message,
        "remediation": remediation,
        "evidence": evidence,
    }
    if extra:
        finding.update(extra)
    return finding


def sort_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    '''按严重级别、路径、行号和规则标识对发现项排序，确保输出稳定。'''
    return sorted(
        findings,
        key=lambda item: (
            SEVERITY_RANK.get(str(item.get("severity")), 99),
            str(item.get("path") or ""),
            item.get("line") if item.get("line") is not None else 10**9,
            str(item.get("rule_id") or ""),
            str(item.get("message") or ""),
        ),
    )


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    '''统计阻断、错误、警告和提示各级别发现的数量。'''
    summary = {"blockers": 0, "errors": 0, "warnings": 0, "infos": 0}
    for finding in findings:
        severity = finding.get("severity")
        if severity == "blocker":
            summary["blockers"] += 1
        elif severity == "error":
            summary["errors"] += 1
        elif severity == "warning":
            summary["warnings"] += 1
        else:
            summary["infos"] += 1
    return summary
