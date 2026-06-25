#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Validate the REMORA cyber evidence v1 dataset."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "evidence" / "cyber_evidence_objects.jsonl"
CASES_PATH = ROOT / "cases" / "security_cases.jsonl"
EXPECTED_PATH = ROOT / "expected_decisions" / "cyber_expected_decisions.jsonl"
POLICY_PATH = ROOT / "policies" / "cyber_triage_rules.yaml"
MANIFEST_PATH = ROOT / "manifest.yaml"

VALID_VERDICTS = {
    "REPORT_READY",
    "NEEDS_REVIEW",
    "LIKELY_FALSE_POSITIVE",
    "ESCALATE",
}

EVIDENCE_REQUIRED = {
    "evidence_id",
    "source",
    "source_url",
    "title",
    "content",
    "domain",
    "risk_tags",
    "authority_score",
    "freshness_score",
    "coverage_score",
    "contradiction_score",
}

PROPRIETARY_MARKERS = {
    "private_customer",
    "customer_secret",
    "scanner_internal_trace",
    "proprietary_rule_id",
    "gostar_private",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} line {line_no}: {exc}") from exc
    return records


class Check:
    def __init__(self, name: str) -> None:
        self.name = name
        self.errors: list[str] = []

    @property
    def passed(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)


def check_evidence_schema(evidence: list[dict[str, Any]]) -> Check:
    check = Check("evidence schema")
    seen: set[str] = set()
    for idx, row in enumerate(evidence, 1):
        eid = str(row.get("evidence_id", f"line_{idx}"))
        missing = EVIDENCE_REQUIRED - row.keys()
        if missing:
            check.error(f"{eid}: missing {sorted(missing)}")
        if eid in seen:
            check.error(f"duplicate evidence_id {eid}")
        seen.add(eid)
        if not str(row.get("source_url", "")).startswith("https://"):
            check.error(f"{eid}: source_url must be https")
        for field in ("authority_score", "freshness_score", "coverage_score", "contradiction_score"):
            try:
                value = float(row.get(field))
            except (TypeError, ValueError):
                check.error(f"{eid}: {field} is not numeric")
                continue
            if not 0.0 <= value <= 1.0:
                check.error(f"{eid}: {field} out of range [0, 1]")
        if row.get("epss_score") is not None:
            epss = float(row["epss_score"])
            if not 0.0 <= epss <= 1.0:
                check.error(f"{eid}: epss_score out of range [0, 1]")
        joined = json.dumps(row, sort_keys=True).lower()
        for marker in PROPRIETARY_MARKERS:
            if marker in joined:
                check.error(f"{eid}: proprietary marker {marker!r} found")
    return check


def check_cases(cases: list[dict[str, Any]], expected: list[dict[str, Any]]) -> Check:
    check = Check("cases and expected decisions")
    case_ids = {str(c.get("case_id")) for c in cases}
    expected_ids = {str(e.get("case_id")) for e in expected}
    for missing in sorted(case_ids - expected_ids):
        check.error(f"case {missing} has no expected decision")
    for unknown in sorted(expected_ids - case_ids):
        check.error(f"expected decision references unknown case {unknown}")
    seen: set[str] = set()
    for case in cases:
        cid = str(case.get("case_id"))
        if cid in seen:
            check.error(f"duplicate case_id {cid}")
        seen.add(cid)
        verdict = str(case.get("expected_verdict", ""))
        if verdict not in VALID_VERDICTS:
            check.error(f"{cid}: invalid expected_verdict {verdict!r}")
        severity = str(case.get("severity", "")).lower()
        if severity in {"critical", "high"} and verdict == "LIKELY_FALSE_POSITIVE":
            check.error(f"{cid}: high-risk case cannot default to LIKELY_FALSE_POSITIVE")
    for row in expected:
        verdict = str(row.get("expected_verdict", ""))
        if verdict not in VALID_VERDICTS:
            check.error(f"expected row {row.get('case_id')}: invalid verdict {verdict!r}")
    return check


def check_policy() -> Check:
    check = Check("policy pack")
    if not POLICY_PATH.exists():
        check.error(f"missing {POLICY_PATH}")
        return check
    if yaml is None:
        return check
    data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    rules = data.get("rules", []) if isinstance(data, dict) else []
    if not rules:
        check.error("no policy rules found")
    for rule in rules:
        for key in ("id", "title", "default_verdict", "governance_action", "required_evidence"):
            if key not in rule:
                check.error(f"rule {rule.get('id', '?')}: missing {key}")
        if rule.get("default_verdict") not in VALID_VERDICTS:
            check.error(f"rule {rule.get('id', '?')}: invalid default_verdict")
    return check


def check_manifest() -> Check:
    check = Check("manifest")
    if not MANIFEST_PATH.exists():
        check.error("manifest.yaml missing")
        return check
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    for required in (
        "contains_proprietary_scanner_data: false",
        "contains_private_findings: false",
        "cyber_evidence_objects.jsonl",
    ):
        if required not in text:
            check.error(f"manifest missing {required!r}")
    return check


def run_checks() -> list[Check]:
    evidence = load_jsonl(EVIDENCE_PATH)
    cases = load_jsonl(CASES_PATH)
    expected = load_jsonl(EXPECTED_PATH)
    return [
        check_evidence_schema(evidence),
        check_cases(cases, expected),
        check_policy(),
        check_manifest(),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate cyber_evidence_v1")
    parser.add_argument("--summary", action="store_true", help="Print summary only")
    args = parser.parse_args()

    checks = run_checks()
    if not args.summary:
        for check in checks:
            status = "PASS" if check.passed else "FAIL"
            print(f"[{status}] {check.name}")
            for err in check.errors:
                print(f"  ERROR: {err}", file=sys.stderr)

    failed = [c for c in checks if not c.passed]
    print(f"Checks: {len(checks)} | Failed: {len(failed)}")
    if failed:
        sys.exit(1)
    print("OK: cyber_evidence_v1 is valid")


if __name__ == "__main__":
    main()
