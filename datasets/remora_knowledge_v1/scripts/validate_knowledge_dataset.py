#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Validate the REMORA knowledge dataset for structural and semantic integrity.

Usage
-----
    python datasets/remora_knowledge_v1/scripts/validate_knowledge_dataset.py
    python datasets/remora_knowledge_v1/scripts/validate_knowledge_dataset.py --strict
    python datasets/remora_knowledge_v1/scripts/validate_knowledge_dataset.py --summary

Exit codes
----------
    0   All checks pass
    1   One or more checks failed (details printed to stderr)

Invariants checked
------------------
INV-1  Every scenario has a corresponding expected gate decision (same scenario_id).
INV-2  Every expected gate decision references a scenario that exists.
INV-3  Evidence objects have all required fields with valid types.
INV-4  No high/critical destructive action has expected gate == "accept".
INV-5  Decision distribution contains all four outcomes (accept/verify/abstain/escalate).
INV-6  Evidence authority_score, freshness_score, coverage_score are in [0, 1].
INV-7  No duplicate scenario_ids or evidence_ids.
INV-8  Replay log entries reference known scenario_ids (when scenario_id is set).
INV-9  Gate rules YAML parses without error; each rule has required keys.
INV-10 Risk-tier mapping YAML parses and defines all four tiers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]

SCENARIOS_PATH = _ROOT / "scenarios" / "agent_action_scenarios.jsonl"
EXPECTED_PATH = _ROOT / "expected_decisions" / "expected_gate_decisions.jsonl"
EVIDENCE_PATH = _ROOT / "evidence_packs" / "evidence_objects.jsonl"
REPLAY_PATH = _ROOT / "replay_logs" / "shadow_replay_demo.jsonl"
GATE_RULES_PATH = _ROOT / "policies" / "remora_gate_rules.yaml"
RISK_TIER_PATH = _ROOT / "policies" / "risk_tier_mapping.yaml"

# ---------------------------------------------------------------------------
# Load helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} line {i}: {exc}") from exc
    return records


def _load_yaml(path: Path) -> Any:
    if not _YAML_OK:
        return None
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _expected_gate(record: dict[str, Any]) -> str:
    """Return the canonical expected gate/action field.

    The locked dataset uses ``expected_gate``. Older unit fixtures used
    ``expected_decision``. Supporting both keeps the validator backward
    compatible while validating the committed artifact.
    """

    return str(record.get("expected_gate") or record.get("expected_decision") or "").lower()


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_inv1_inv2(scenarios: list, expected: list) -> CheckResult:
    r = CheckResult("INV-1/2  scenario <-> expected_decision bijection")
    s_ids = {s.get("scenario_id") for s in scenarios}
    e_ids = {e.get("scenario_id") for e in expected}
    for sid in sorted(s_ids - e_ids):
        r.error(f"scenario {sid!r} has no expected_decision")
    for eid in sorted(e_ids - s_ids):
        r.error(f"expected_decision {eid!r} references unknown scenario")
    return r


def check_inv3_evidence_fields(evidence: list) -> CheckResult:
    r = CheckResult("INV-3  Evidence object required fields")
    required = {
        "evidence_id", "source", "title", "content", "domain",
        "risk_tags", "authority_score", "freshness_score",
        "coverage_score", "contradiction_score",
    }
    for i, obj in enumerate(evidence, 1):
        missing = required - obj.keys()
        if missing:
            r.error(f"evidence_objects line {i} ({obj.get('evidence_id','?')}): missing {sorted(missing)}")
    return r


def check_inv4_no_accept_for_destructive(scenarios: list, expected: list) -> CheckResult:
    r = CheckResult("INV-4  No high/critical destructive action -> ACCEPT")
    e_map = {e.get("scenario_id"): _expected_gate(e) for e in expected}
    for s in scenarios:
        sid = s.get("scenario_id", "?")
        tier = (s.get("risk_tier") or "").lower()
        atype = (s.get("action_type") or "").lower()
        decision = e_map.get(sid, "")
        if tier in ("high", "critical") and "destructive" in atype and decision == "accept":
            r.error(
                f"scenario {sid!r}: tier={tier} action_type={atype!r} but expected_gate=accept"
            )
    return r


def check_inv5_decision_distribution(expected: list) -> CheckResult:
    r = CheckResult("INV-5  Decision distribution covers all four outcomes")
    outcomes = {_expected_gate(e) for e in expected}
    for required in ("accept", "verify", "abstain", "escalate"):
        if required not in outcomes:
            r.error(f"no expected gate with outcome '{required}' found")
    return r


def check_inv6_scores_in_range(evidence: list) -> CheckResult:
    r = CheckResult("INV-6  Evidence scores in [0, 1]")
    score_fields = ("authority_score", "freshness_score", "coverage_score", "contradiction_score")
    for i, obj in enumerate(evidence, 1):
        eid = obj.get("evidence_id", f"line {i}")
        for field in score_fields:
            val = obj.get(field)
            if val is not None:
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    r.error(f"{eid}: {field}={val!r} is not numeric")
                    continue
                if not (0.0 <= fval <= 1.0):
                    r.error(f"{eid}: {field}={fval} out of range [0, 1]")
    return r


def check_inv7_no_duplicates(scenarios: list, evidence: list) -> CheckResult:
    r = CheckResult("INV-7  No duplicate scenario_ids or evidence_ids")
    seen_s: dict[str, int] = {}
    for i, s in enumerate(scenarios, 1):
        sid = s.get("scenario_id")
        if sid in seen_s:
            r.error(f"duplicate scenario_id {sid!r} (first at line {seen_s[sid]}, again at {i})")
        else:
            seen_s[sid] = i
    seen_e: dict[str, int] = {}
    for i, e in enumerate(evidence, 1):
        eid = e.get("evidence_id")
        if eid in seen_e:
            r.error(f"duplicate evidence_id {eid!r} (first at line {seen_e[eid]}, again at {i})")
        else:
            seen_e[eid] = i
    return r


def check_inv8_replay_scenario_refs(replay: list, scenarios: list) -> CheckResult:
    r = CheckResult("INV-8  Replay entries reference known scenario_ids")
    known = {s.get("scenario_id") for s in scenarios}
    for i, entry in enumerate(replay, 1):
        sid = entry.get("scenario_id")
        if sid and sid not in known:
            r.warn(f"replay line {i}: scenario_id {sid!r} not in scenarios (may be extended set)")
    return r


def check_inv9_gate_rules(path: Path) -> CheckResult:
    r = CheckResult("INV-9  gate_rules.yaml parses; each rule has required keys")
    if not path.exists():
        r.error(f"file not found: {path}")
        return r
    if not _YAML_OK:
        r.warn("PyYAML not installed - skipping YAML validation")
        return r
    data = _load_yaml(path)
    rules = data.get("gate_rules") or data.get("rules", []) if isinstance(data, dict) else []
    if not rules:
        r.error("no gate_rules entries found")
        return r
    required_keys = {"id", "title", "default_gate", "applies_to"}
    for rule in rules:
        missing = required_keys - rule.keys()
        if missing:
            r.error(f"rule {rule.get('id', rule.get('rule_id', '?'))}: missing keys {sorted(missing)}")
    return r


def check_inv10_risk_tiers(path: Path) -> CheckResult:
    r = CheckResult("INV-10 risk_tier_mapping.yaml defines all four tiers")
    if not path.exists():
        r.error(f"file not found: {path}")
        return r
    if not _YAML_OK:
        r.warn("PyYAML not installed - skipping YAML validation")
        return r
    data = _load_yaml(path)
    tiers = data.get("risk_tiers") or data.get("tiers", {}) if isinstance(data, dict) else {}
    for required in ("low", "medium", "high", "critical"):
        if required not in tiers:
            r.error(f"risk_tier_mapping.yaml missing tier '{required}'")
    return r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all_checks(strict: bool = False) -> tuple[list[CheckResult], bool]:
    # Load data
    load_errors = []
    scenarios = expected = evidence = replay = []
    try:
        scenarios = _load_jsonl(SCENARIOS_PATH)
        expected = _load_jsonl(EXPECTED_PATH)
        evidence = _load_jsonl(EVIDENCE_PATH)
        replay = _load_jsonl(REPLAY_PATH)
    except ValueError as exc:
        load_errors.append(str(exc))

    results: list[CheckResult] = []

    if load_errors:
        r = CheckResult("LOAD  Parse JSONL files")
        for e in load_errors:
            r.error(e)
        results.append(r)
        return results, False

    results += [
        check_inv1_inv2(scenarios, expected),
        check_inv3_evidence_fields(evidence),
        check_inv4_no_accept_for_destructive(scenarios, expected),
        check_inv5_decision_distribution(expected),
        check_inv6_scores_in_range(evidence),
        check_inv7_no_duplicates(scenarios, evidence),
        check_inv8_replay_scenario_refs(replay, scenarios),
        check_inv9_gate_rules(GATE_RULES_PATH),
        check_inv10_risk_tiers(RISK_TIER_PATH),
    ]

    # In strict mode, warnings are promoted to errors
    if strict:
        for r in results:
            r.errors.extend(r.warnings)
            r.warnings.clear()

    all_passed = all(r.passed for r in results)
    return results, all_passed


def print_report(results: list[CheckResult], summary_only: bool = False) -> None:
    n_pass = sum(1 for r in results if r.passed)
    n_fail = len(results) - n_pass
    n_warn = sum(len(r.warnings) for r in results)

    if not summary_only:
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.name}")
            for err in r.errors:
                print(f"         ERROR: {err}", file=sys.stderr)
            for w in r.warnings:
                print(f"         WARN:  {w}")

    print(f"\n  Checks: {len(results)}  |  Passed: {n_pass}  |  Failed: {n_fail}  |  Warnings: {n_warn}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate REMORA knowledge dataset")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    parser.add_argument("--summary", action="store_true", help="Print summary only")
    args = parser.parse_args()

    print("REMORA Knowledge Dataset Validator")
    print("=" * 50)

    results, passed = run_all_checks(strict=args.strict)
    print_report(results, summary_only=args.summary)

    if passed:
        print("\n  OK: All invariants satisfied.\n")
        sys.exit(0)
    else:
        print("\n  ERROR: Validation FAILED - see errors above.\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
