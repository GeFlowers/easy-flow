'''检查技能包结构、元数据、资源引用和安全扫描结果，并汇总为稳定的审查事实。'''

from __future__ import annotations

import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from deerflow.skills.frontmatter import ALLOWED_FRONTMATTER_PROPERTIES, split_skill_markdown
from deerflow.skills.package_paths import is_eval_fixture_path, is_eval_fixture_skill_md
from deerflow.skills.parser import parse_allowed_tools, parse_required_secrets
from deerflow.skills.review.digest import compute_package_digest
from deerflow.skills.review.eval_schema import analyze_eval_manifests
from deerflow.skills.review.models import (
    FACTS_SCHEMA_VERSION,
    SKILLSCAN_SEVERITY_MAP,
    ProfileName,
    make_finding,
    sort_findings,
    summarize_findings,
)
from deerflow.skills.review.resource_graph import build_resource_graph
from deerflow.skills.skillscan.orchestrator import scan_skill_dir


def analyze_skill_package(snapshot: dict[str, Any], *, profile: ProfileName = "deerflow") -> dict[str, Any]:
    '''串联结构校验、资源图分析和静态扫描，生成供审查界面消费的事实、错误与完整度信息。'''
    findings: list[dict[str, Any]] = []
    analyzer_errors: list[dict[str, Any]] = []
    files = {str(entry["path"]): entry for entry in snapshot.get("files", [])}

    skill_entries = [path for path in files if PurePosixPath(path).name == "SKILL.md"]
    root_skill = files.get("SKILL.md")
    declared_name = None
    text_complete = not snapshot.get("truncated")
    not_assessed: list[str] = []

    if not root_skill:
        findings.append(
            make_finding(
                "structure.missing-skill-md",
                severity="blocker",
                message="技能包根目录不包含 SKILL.md。",
                remediation="在技能包根目录添加且仅添加一个 SKILL.md。",
            )
        )
    elif root_skill.get("kind") != "text":
        findings.append(
            make_finding(
                "structure.skill-md-not-text",
                severity="blocker",
                path="SKILL.md",
                message="根目录的 SKILL.md 不是可读取的统一码转换格式八位文本。",
                remediation="将 SKILL.md 保存为统一码转换格式八位的 Markdown 文本，并包含前置元数据。",
            )
        )
    else:
        declared_name = _analyze_skill_md(str(root_skill.get("content") or ""), profile=profile, findings=findings)

    for nested in sorted(path for path in skill_entries if path != "SKILL.md" and not is_eval_fixture_skill_md(path)):
        findings.append(
            make_finding(
                "structure.nested-skill-md",
                severity="blocker",
                path=nested,
                message="单个技能包中不允许嵌套 SKILL.md 文件。",
                remediation="在技能包根目录保留且仅保留一个 SKILL.md。",
            )
        )

    for path, entry in files.items():
        if entry.get("kind") == "symlink":
            findings.append(
                make_finding(
                    "package.symlink",
                    severity="warning",
                    path=path,
                    message="技能包包含符号链接条目。",
                    remediation="将符号链接替换为技能包内部的普通文件。",
                    evidence=entry.get("target"),
                )
            )
        if _is_nested_archive(path):
            findings.append(
                make_finding(
                    "package.nested-archive",
                    severity="warning",
                    path=path,
                    message="技能包包含嵌套归档。",
                    remediation="打包技能前请解压并审查嵌套归档。",
                )
            )
        if _is_hidden_sensitive_path(path):
            findings.append(
                make_finding(
                    "package.hidden-sensitive-file",
                    severity="warning",
                    path=path,
                    message="技能包包含隐藏的敏感文件。",
                    remediation="移除隐藏的凭据文件或包管理器配置文件。",
                )
            )

    resource_graph, resource_findings = build_resource_graph(snapshot)
    findings.extend(resource_findings)

    evals, eval_findings = analyze_eval_manifests(snapshot)
    findings.extend(eval_findings)

    try:
        findings.extend(_scan_with_skillscan(snapshot))
    except Exception as exc:
        analyzer_errors.append({"code": "skillscan_failed", "path": None, "message": type(exc).__name__})
        not_assessed.append("skillscan")

    if snapshot.get("truncated"):
        not_assessed.append("full_package")

    findings = sort_findings(findings)
    package_digest = compute_package_digest(snapshot)
    subject = {
        "display_ref": snapshot.get("subject", {}).get("display_ref"),
        "source": snapshot.get("subject", {}).get("source"),
        "category": snapshot.get("subject", {}).get("category"),
        "declared_name": declared_name,
        "package_digest": package_digest,
    }
    return {
        "schema_version": FACTS_SCHEMA_VERSION,
        "subject": subject,
        "profile": profile,
        "completeness": {
            "package_enumerated": not any(error.get("code") == "root_not_found" for error in snapshot.get("reader_errors", [])),
            "text_content_complete": text_complete,
            "truncated": bool(snapshot.get("truncated")),
            "not_assessed": sorted(set(not_assessed)),
        },
        "summary": summarize_findings(findings),
        "findings": findings,
        "resources": resource_graph,
        "evals": evals,
        "reader_errors": snapshot.get("reader_errors", []),
        "analyzer_errors": analyzer_errors,
    }


def _analyze_skill_md(content: str, *, profile: ProfileName, findings: list[dict[str, Any]]) -> str | None:
    '''解析根目录技能说明，校验头部元数据和正文要求，并把违反项追加到发现列表。'''
    parts, error = split_skill_markdown(content)
    if error or parts is None:
        findings.append(
            make_finding(
                "structure.invalid-frontmatter",
                severity="blocker",
                path="SKILL.md",
                message=error or "前置元数据格式无效.",
                remediation="使用以 --- 分隔的前置元数据，并包含 name 和 description 字段。",
            )
        )
        return None

    metadata = parts.metadata
    unexpected = sorted(set(metadata) - ALLOWED_FRONTMATTER_PROPERTIES)
    if unexpected:
        findings.append(
            make_finding(
                "structure.unknown-frontmatter-field",
                severity="warning",
                path="SKILL.md",
                message=f"未知的前置元数据字段： {', '.join(unexpected)}",
                remediation="移除不支持的字段，或将其添加到共享的 DeerFlow 前置元数据模式中。",
                evidence=unexpected,
            )
        )

    name = metadata.get("name")
    declared_name = name.strip() if isinstance(name, str) else None
    if not declared_name:
        findings.append(
            make_finding(
                "structure.missing-name",
                severity="blocker",
                path="SKILL.md",
                message="前置元数据缺少非空的 name。",
                remediation="添加使用连字符命名的技能名称。",
            )
        )
    elif not _valid_skill_name(declared_name):
        findings.append(
            make_finding(
                "structure.invalid-name",
                severity="error",
                path="SKILL.md",
                message="技能名称必须采用连字符命名，仅使用小写字母、数字和连字符。",
                remediation="使用小写字母和连字符重新命名技能。",
                evidence=declared_name,
            )
        )

    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        findings.append(
            make_finding(
                "structure.missing-description",
                severity="blocker",
                path="SKILL.md",
                message="前置元数据缺少非空的 description。",
                remediation="添加简明描述，说明技能的用途和调用时机。",
            )
        )
    elif len(description.strip()) > 1024:
        findings.append(
            make_finding(
                "structure.description-too-long",
                severity="error",
                path="SKILL.md",
                message="描述超过 DeerFlow 的 1024 字符限制。",
                remediation="缩短描述，将详细指导移到正文中。",
            )
        )

    body = parts.body.strip()
    if not body:
        findings.append(
            make_finding(
                "structure.empty-body",
                severity="error",
                path="SKILL.md",
                message="SKILL.md 的前置元数据后没有指令正文。",
                remediation="在前置元数据后添加可执行的工作流程说明。",
            )
        )

    try:
        parse_allowed_tools(metadata.get("allowed-tools"), Path("SKILL.md"))
    except ValueError as exc:
        findings.append(
            make_finding(
                "structure.invalid-allowed-tools",
                severity="error",
                path="SKILL.md",
                message=str(exc),
                remediation="将 allowed-tools 声明为非空字符串列表。",
            )
        )

    try:
        parse_required_secrets(metadata.get("required-secrets"), Path("SKILL.md"))
    except ValueError as exc:
        findings.append(
            make_finding(
                "structure.invalid-required-secrets",
                severity="error",
                path="SKILL.md",
                message=str(exc),
                remediation="将 required-secrets 声明为列表。",
            )
        )

    if "secrets-autonomous" in metadata and not isinstance(metadata.get("secrets-autonomous"), bool):
        findings.append(
            make_finding(
                "structure.invalid-secrets-autonomous",
                severity="error",
                path="SKILL.md",
                message="secrets-autonomous 必须为布尔值.",
                remediation="为 secrets-autonomous 使用 true 或 false。",
            )
        )

    if profile == "agentskills":
        _add_agentskills_findings(metadata, declared_name, findings)

    return declared_name


def _add_agentskills_findings(metadata: dict[str, Any], declared_name: str | None, findings: list[dict[str, Any]]) -> None:
    '''补充技能可移植性检查中的名称和描述长度提示。'''
    description = metadata.get("description")
    if isinstance(description, str) and len(description.strip()) > 200:
        findings.append(
            make_finding(
                "agentskills.description-length",
                severity="warning",
                source="review-core",
                profile="agentskills",
                path="SKILL.md",
                message="描述超过代理技能规范建议的显示长度。",
                remediation="保持描述简明，将详细内容移到正文。",
            )
        )
    if declared_name and len(declared_name) > 64:
        findings.append(
            make_finding(
                "agentskills.name-length",
                severity="warning",
                source="review-core",
                profile="agentskills",
                path="SKILL.md",
                message="技能名称超过可移植性配置建议的长度。",
                remediation="使用更短的包名以便跨客户端使用。",
            )
        )


def _scan_with_skillscan(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    '''将快照中的文本文件写入临时目录执行静态扫描，再把结果转换为统一发现项。'''
    files = [entry for entry in snapshot.get("files", []) if entry.get("kind") == "text" and not is_eval_fixture_path(str(entry.get("path") or ""))]
    if not files:
        return []
    with tempfile.TemporaryDirectory(prefix="skill-review-") as tmp:
        root = Path(tmp)
        for entry in files:
            rel = str(entry["path"])
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(entry.get("content") or ""), encoding="utf-8")
        result = scan_skill_dir(root)
    findings: list[dict[str, Any]] = []
    for finding in result.get("findings", []):
        severity = SKILLSCAN_SEVERITY_MAP.get(str(finding.get("severity")), "warning")
        findings.append(
            make_finding(
                str(finding.get("rule_id")),
                source="skillscan",
                profile="deerflow",
                severity=severity,
                path=finding.get("file"),
                line=finding.get("line"),
                message=str(finding.get("message")),
                remediation=str(finding.get("remediation")),
                evidence=finding.get("evidence"),
                extra={"skillscan_severity": finding.get("severity")},
            )
        )
    for error in result.get("scanner_errors", []):
        findings.append(
            make_finding(
                "skillscan.scanner-error",
                source="skillscan",
                severity="warning",
                message="技能扫描报告了分析器错误。",
                remediation="检查所引用的文件，并重新运行审查。",
                evidence=str(error),
            )
        )
    return findings


def _valid_skill_name(name: str) -> bool:
    '''判断技能名是否符合小写字母、数字和连字符组成的命名规则及长度上限。'''
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)) and len(name) <= 64


def _is_nested_archive(path: str) -> bool:
    '''识别技能包内可能隐藏额外内容的压缩包或分发归档文件。'''
    lowered = path.lower()
    return lowered.endswith((".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".7z", ".rar", ".whl"))


def _is_hidden_sensitive_path(path: str) -> bool:
    '''检查路径各级是否包含常见凭据或包管理器配置文件。'''
    parts = PurePosixPath(path).parts
    return any(part in {".env", ".npmrc", ".pypirc", ".netrc"} for part in parts)
