#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""CLI runner for REMORA Shadow Mode replay."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the repo root is on the path so that `remora` is importable when this
# script is invoked directly (e.g. `python scripts/shadow_replay.py`) without
# the package being installed in the active Python environment.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from remora.shadow.replay import replay_action_log


def main() -> None:
    parser = argparse.ArgumentParser(description="REMORA Shadow Mode replay")
    parser.add_argument("--input", required=True, help="Input action log JSONL")
    parser.add_argument(
        "--envelopes-out",
        default="artifacts/shadow_mode/decision_envelopes.jsonl",
        help="Output path for DecisionEnvelope JSONL",
    )
    parser.add_argument(
        "--report-out",
        default="artifacts/shadow_mode/governance_delta_report.json",
        help="Output path for governance delta report JSON",
    )
    parser.add_argument(
        "--audit-out",
        default="artifacts/shadow_mode/replay_audit.jsonl",
        help="Optional audit JSONL path for hash-chain logging",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help=(
            "Directory for replay outputs. When set, writes "
            "decision_envelopes.jsonl, governance_delta_report.json, and replay_audit.jsonl there."
        ),
    )
    args = parser.parse_args()

    envelopes_out = args.envelopes_out
    report_out = args.report_out
    audit_out = args.audit_out
    if args.out_dir:
        out_dir = Path(args.out_dir)
        envelopes_out = str(out_dir / "decision_envelopes.jsonl")
        report_out = str(out_dir / "governance_delta_report.json")
        audit_out = str(out_dir / "replay_audit.jsonl")

    result = replay_action_log(
        args.input,
        output_envelopes_jsonl=envelopes_out,
        output_report_json=report_out,
        output_audit_jsonl=audit_out,
    )

    r = result.report
    print("REMORA Governance Delta Report")
    print()
    print(f"Total actions reviewed: {r.total_actions_reviewed}")
    print(f"Accepted: {r.accepted}")
    print(f"Verify required: {r.verify_required}")
    print(f"Abstained: {r.abstained}")
    print(f"Escalated: {r.escalated}")
    print()
    print(f"Critical actions proposed: {r.critical_actions_proposed}")
    print(f"Critical autonomous accepts: {r.critical_autonomous_accepts}")
    print(f"Policy violations detected: {r.policy_violations_detected}")
    print(f"Missing evidence cases: {r.missing_evidence_cases}")
    print(f"Oracle disagreement cases: {r.oracle_disagreement_cases}")
    print(f"Audit completeness: {r.audit_completeness_pct:.1f} %")
    print()
    print(f"Estimated avoided unsafe executions: {r.estimated_avoided_unsafe_executions}")
    print(f"Utility retained: {r.utility_retained_pct:.1f} %")
    print(f"Human-review burden: {r.human_review_burden_pct:.1f} %")
    print()
    print("Baseline comparison:")
    print(json.dumps(r.baseline_comparison, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
