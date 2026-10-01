'''定义技能静态安全扫描器共享的发现项、结果和阻止异常数据结构。

Data contracts for DeerFlow SkillScan.

Every ``SecurityFinding`` field has a Phase 1 consumer: the blocking policy
reads ``severity``; the Gateway rejection response, the agent tool error, and
the LLM scanner context read the rest. The rule category and owning analyzer
are encoded in the ``rule_id`` prefix (``package-``, ``secret-``,
``declaration-``, ``python-``, ``shell-``, ``network-``/``resource-``), not
duplicated as separate fields.
'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

FindingSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class SecurityFinding(TypedDict):
    '''描述一条安全规则发现及其位置、说明、证据和修复建议。'''

    rule_id: str
    severity: FindingSeverity
    file: str | None
    line: int | None
    message: str
    remediation: str
    evidence: str | None


class ScanResult(TypedDict):
    '''汇总扫描发现、是否阻止操作及扫描器自身错误。'''

    findings: list[SecurityFinding]
    blocked: bool
    scanner_errors: list[str]


@dataclass(frozen=True)
class RuleSpec:
    '''保存一条静态扫描规则的标识、严重等级、说明和修复指引。'''

    rule_id: str
    severity: FindingSeverity
    message: str
    remediation: str


class StaticScannerError(RuntimeError):
    '''表示扫描器在技能包边界处无法完成输入评估。'''


class StaticScanBlockedError(ValueError):
    '''携带阻止写入或安装的确定性扫描发现。'''

    findings: list[SecurityFinding]
    skill_name: str | None

    def __init__(self, findings: list[SecurityFinding], *, skill_name: str | None = None, message: str | None = None) -> None:
        '''复制扫描发现并保存技能名，供路由和工具展示拦截原因。'''
        self.findings = [dict(finding) for finding in findings]  # type: ignore[list-item]
        self.skill_name = skill_name
        subject = f"skill '{skill_name}'" if skill_name else "skill content"
        super().__init__(message or f"Static security scan blocked {subject}")
