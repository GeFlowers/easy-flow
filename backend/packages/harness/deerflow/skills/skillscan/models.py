"""定义 models 模块提供的职责与可复用接口。

Data contracts for DeerFlow SkillScan.

Every ``SecurityFinding`` field has a Phase 1 consumer: the blocking policy
reads ``severity``; the Gateway rejection response, the agent tool error, and
the LLM scanner context read the rest. The rule category and owning analyzer
are encoded in the ``rule_id`` prefix (``package-``, ``secret-``,
``declaration-``, ``python-``, ``shell-``, ``network-``/``resource-``), not
duplicated as separate fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

FindingSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class SecurityFinding(TypedDict):
    "封装 SecurityFinding 的状态、协作关系与公开操作"

    rule_id: str
    severity: FindingSeverity
    file: str | None
    line: int | None
    message: str
    remediation: str
    evidence: str | None


class ScanResult(TypedDict):
    "封装 ScanResult 的状态、协作关系与公开操作"

    findings: list[SecurityFinding]
    blocked: bool
    scanner_errors: list[str]


@dataclass(frozen=True)
class RuleSpec:
    """封装 RuleSpec 的状态、协作关系与公开操作。

    Static definition of one SkillScan rule; ``remediation`` is authored here once and copied into findings."""

    rule_id: str
    severity: FindingSeverity
    message: str
    remediation: str


class StaticScannerError(RuntimeError):
    """封装 StaticScannerError 的状态、协作关系与公开操作。

    Raised when SkillScan cannot evaluate its input at the package boundary."""


class StaticScanBlockedError(ValueError):
    """封装 StaticScanBlockedError 的状态、协作关系与公开操作。

    Raised when deterministic findings block a skill write or install."""

    findings: list[SecurityFinding]
    skill_name: str | None

    def __init__(self, findings: list[SecurityFinding], *, skill_name: str | None = None, message: str | None = None) -> None:
        "实现 __init__ 协议方法，保持对象交互语义一致"
        self.findings = [dict(finding) for finding in findings]  # type: ignore[list-item]
        self.skill_name = skill_name
        subject = f"skill '{skill_name}'" if skill_name else "skill content"
        super().__init__(message or f"Static security scan blocked {subject}")
