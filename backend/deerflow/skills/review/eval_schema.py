'''识别技能包内的评测清单格式，并汇总用例数量及触发正反例统计。'''

from __future__ import annotations

import json
from typing import Any

from deerflow.skills.review.models import make_finding


def analyze_eval_manifests(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    '''解析所有 evals 下的 JSON 清单，收集格式错误并汇总各清单统计信息。'''
    files = {str(entry["path"]): entry for entry in snapshot.get("files", [])}
    eval_files = [path for path in sorted(files) if path.startswith("evals/") and path.endswith(".json")]
    findings: list[dict[str, Any]] = []
    aggregate = {
        "schema": None,
        "valid": None,
        "case_count": 0,
        "positive_trigger_cases": 0,
        "negative_trigger_cases": 0,
        "manifests": [],
    }
    if not eval_files:
        return aggregate, findings

    schemas: set[str] = set()
    valid = True
    for path in eval_files:
        entry = files[path]
        if entry.get("kind") != "text":
            findings.append(
                make_finding(
                    "eval.binary-manifest",
                    severity="warning",
                    path=path,
                    message="Eval manifest is not UTF-8 JSON text.",
                    remediation="Store eval manifests as UTF-8 JSON.",
                )
            )
            valid = False
            continue
        try:
            payload = json.loads(str(entry.get("content") or ""))
        except json.JSONDecodeError as exc:
            findings.append(
                make_finding(
                    "eval.invalid-json",
                    severity="warning",
                    path=path,
                    line=exc.lineno,
                    message="Eval manifest is not valid JSON.",
                    remediation="Fix the JSON syntax or remove the manifest.",
                    evidence=exc.msg,
                )
            )
            valid = False
            continue
        manifest = _classify_manifest(payload)
        manifest["path"] = path
        aggregate["manifests"].append(manifest)
        schemas.add(manifest["schema"])
        aggregate["case_count"] += manifest["case_count"]
        aggregate["positive_trigger_cases"] += manifest["positive_trigger_cases"]
        aggregate["negative_trigger_cases"] += manifest["negative_trigger_cases"]

    if schemas:
        aggregate["schema"] = next(iter(schemas)) if len(schemas) == 1 else "mixed"
    aggregate["valid"] = valid
    return aggregate, findings


def _classify_manifest(payload: Any) -> dict[str, Any]:
    '''识别版本化、技能创建器或旧式列表清单，并统一成统计结构。'''
    if isinstance(payload, dict) and isinstance(payload.get("schema_version"), str):
        cases = payload.get("cases")
        if isinstance(cases, list):
            return _case_stats("versioned", cases)
        return {"schema": "versioned", "valid": True, "case_count": 0, "positive_trigger_cases": 0, "negative_trigger_cases": 0}

    if isinstance(payload, dict) and isinstance(payload.get("evals"), list):
        return _case_stats("skill-creator-evals", payload["evals"])

    if isinstance(payload, list):
        return _case_stats("trigger-eval-list", payload)

    return {"schema": "unknown", "valid": True, "case_count": 0, "positive_trigger_cases": 0, "negative_trigger_cases": 0}


def _case_stats(schema: str, cases: list[Any]) -> dict[str, Any]:
    '''统计用例总数及明确标记为应触发或不应触发的用例数。'''
    positive = 0
    negative = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        should_trigger = case.get("should_trigger")
        if should_trigger is True:
            positive += 1
        elif should_trigger is False:
            negative += 1
    return {
        "schema": schema,
        "valid": True,
        "case_count": len(cases),
        "positive_trigger_cases": positive,
        "negative_trigger_cases": negative,
    }
