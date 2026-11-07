'''根据技能包审查事实生成就绪度、报告结构和本地化 Markdown 摘要。'''

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from deerflow.skills.review.models import REPORT_SCHEMA_VERSION

Readiness = Literal["blocked", "revise", "publish_candidate"]
Assurance = Literal["static_only", "trigger_checked", "behavior_verified", "regression_verified"]
Locale = Literal["en", "zh"]

_READINESS_LABELS = {
    "en": {
        "blocked": "不可发布",
        "revise": "需修订",
        "publish_candidate": "可作为发布候选",
    },
    "zh": {
        "blocked": "不可发布",
        "revise": "需修订",
        "publish_candidate": "可作为发布候选",
    },
}

_ASSURANCE_LABELS = {
    "en": {
        "static_only": "仅静态审查",
        "trigger_checked": "触发已检查",
        "behavior_verified": "行为已验证",
        "regression_verified": "回归已验证",
    },
    "zh": {
        "static_only": "仅静态审查",
        "trigger_checked": "触发已检查",
        "behavior_verified": "行为已验证",
        "regression_verified": "回归已验证",
    },
}


def readiness_from_facts(facts: dict[str, Any], *, scope: list[str] | None = None) -> Readiness:
    '''依据阻断项、错误项和未评估范围判定包是否可发布。'''
    summary = facts.get("summary", {})
    if int(summary.get("blockers") or 0) > 0:
        return "blocked"
    if int(summary.get("errors") or 0) > 0:
        return "revise"
    if scope and "all" in scope and facts.get("completeness", {}).get("not_assessed"):
        return "revise"
    return "publish_candidate"


def build_static_report(
    facts: dict[str, Any],
    *,
    scope: list[str] | None = None,
    reviewer_model: str = "deterministic-review-core",
    completed_at: str | None = None,
) -> dict[str, Any]:
    '''仅根据确定性扫描事实生成静态审查报告及其证据和建议。'''
    scope = scope or ["all"]
    readiness = readiness_from_facts(facts, scope=scope)
    issues = [
        {
            "id": f"deterministic.{idx + 1}.{finding['rule_id']}",
            "severity": _semantic_severity(finding.get("severity")),
            "confidence": "high",
            "path": finding.get("path"),
            "line": finding.get("line"),
            "problem": finding.get("message"),
            "impact": "确定性审查发现项影响技能包的发布就绪度或可维护性。",
            "remediation": finding.get("remediation"),
            "suggested_replacement": None,
        }
        for idx, finding in enumerate(facts.get("findings", []))
        if finding.get("severity") in {"blocker", "error", "warning"}
    ]
    dimensions = _dimensions_from_facts(facts)
    limitations = []
    if facts.get("completeness", {}).get("truncated"):
        limitations.append("技能包内容已截断；省略部分未进行评估。")
    for error in facts.get("reader_errors", []):
        limitations.append(f"读取器错误 {error.get('code')}: {error.get('message')}")
    for error in facts.get("analyzer_errors", []):
        limitations.append(f"分析器错误 {error.get('code')}: {error.get('message')}")

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "subject": {
            "display_ref": facts.get("subject", {}).get("display_ref"),
            "package_digest": facts.get("subject", {}).get("package_digest"),
        },
        "review": {
            "scope": scope,
            "profile": facts.get("profile", "deerflow"),
            "facts_schema_version": facts.get("schema_version"),
            "reviewer_model": reviewer_model,
            "completed_at": completed_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
        "readiness": readiness,
        "assurance": "static_only",
        "dimensions": dimensions,
        "issues": issues,
        "evidence": {
            "facts_complete": not facts.get("completeness", {}).get("truncated"),
            "runtime_runs": [],
            "baseline": None,
            "retained_artifacts": [],
            "limitations": limitations,
        },
        "recommended_actions": _recommended_actions(facts, readiness),
    }


def render_report_markdown(report: dict[str, Any], facts: dict[str, Any] | None = None, *, locale: Locale = "en") -> str:
    '''按指定语言将结构化审查报告渲染为 Markdown 文本。'''
    labels = _READINESS_LABELS[locale]
    assurance_labels = _ASSURANCE_LABELS[locale]
    zh = locale == "zh"
    lines = [
        "# 技能审查报告" if not zh else "# 技能审查报告",
        "",
        "## 摘要" if not zh else "## 摘要",
        f"- 对象： {report.get('subject', {}).get('display_ref')}",
        f"- 摘要值： {report.get('subject', {}).get('package_digest')}",
        f"- 发布就绪度： {report.get('readiness')} ({labels.get(report.get('readiness'), report.get('readiness'))})",
        f"- 验证程度： {report.get('assurance')} ({assurance_labels.get(report.get('assurance'), report.get('assurance'))})",
        "",
        "## 范围与完整性" if not zh else "## 范围与完整性",
        f"- 范围： {', '.join(report.get('review', {}).get('scope', []))}",
        f"- 配置： {report.get('review', {}).get('profile')}",
    ]
    if facts:
        completeness = facts.get("completeness", {})
        lines.extend(
            [
                f"- 是否截断： {completeness.get('truncated')}",
                f"- 未评估： {', '.join(completeness.get('not_assessed') or []) or '(无)'}",
            ]
        )
    lines.extend(["", "## 问题" if not zh else "## 问题"])
    issues = report.get("issues", [])
    if not issues:
        lines.append("- 未报告确定性问题或语义问题。")
    else:
        for issue in issues:
            location = issue.get("path") or "<package>"
            if issue.get("line") is not None:
                location = f"{location}:{issue['line']}"
            lines.append(f"- {issue.get('severity')} {issue.get('id')}，位置 {location}：{issue.get('problem')}")
    lines.extend(["", "## 维度审查" if not zh else "## 维度审查"])
    for dimension in report.get("dimensions", []):
        lines.append(f"- {dimension.get('id')}: {dimension.get('status')} - {dimension.get('summary')}")
    lines.extend(["", "## 证据" if not zh else "## 证据"])
    evidence = report.get("evidence", {})
    lines.append(f"- 事实是否完整： {evidence.get('facts_complete')}")
    limitations = evidence.get("limitations") or []
    if limitations:
        for limitation in limitations:
            lines.append(f"- 限制： {limitation}")
    lines.extend(["", "## 建议动作" if not zh else "## 建议动作"])
    actions = report.get("recommended_actions") or []
    if not actions:
        lines.append("- 在已评估范围内无需采取动作。")
    else:
        for action in actions:
            lines.append(f"- {action}")
    return "\n".join(lines).rstrip() + "\n"


def _semantic_severity(severity: Any) -> str:
    '''将扫描严重等级映射为审查报告使用的等级。'''
    if severity == "blocker":
        return "blocker"
    if severity == "error":
        return "major"
    return "minor"


def _dimensions_from_facts(facts: dict[str, Any]) -> list[dict[str, Any]]:
    '''根据发现数量和评测样例覆盖情况生成结构与证据质量维度。'''
    summary = facts.get("summary", {})
    status = "blocker" if summary.get("blockers") else "concern" if summary.get("errors") or summary.get("warnings") else "pass"
    return [
        {
            "id": "structure",
            "status": status,
            "summary": f"{summary.get('blockers', 0)} 个阻断项, {summary.get('errors', 0)} 个错误, {summary.get('warnings', 0)} 个警告",
        },
        {
            "id": "evidence_quality",
            "status": "concern" if facts.get("evals", {}).get("case_count", 0) == 0 else "pass",
            "summary": f"{facts.get('evals', {}).get('case_count', 0)} 个评测用例",
        },
    ]


def _recommended_actions(facts: dict[str, Any], readiness: str) -> list[str]:
    '''候选包无需补救动作；其他状态列出最前面的修复建议。'''
    if readiness == "publish_candidate":
        return []
    actions: list[str] = []
    for finding in facts.get("findings", [])[:5]:
        actions.append(f"{finding.get('rule_id')}: {finding.get('remediation')}")
    return actions
