#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Run the REMORA cross-domain governance benchmark.

Usage
-----
    python scripts/run_domain_benchmark.py
    python scripts/run_domain_benchmark.py --domain cyber
    python scripts/run_domain_benchmark.py --domain ai_governance
    python scripts/run_domain_benchmark.py --domain finance
    python scripts/run_domain_benchmark.py --out artifacts/domain_benchmark_results.json

The benchmark is deterministic and requires no API keys.  Results are written
to the specified JSON file and also printed to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from remora.evidence.benchmark import BenchmarkCase, DomainBenchmarkResult


def _run_cyber() -> "DomainBenchmarkResult":
    from remora.evidence.cyber import CyberEvidenceProvider
    from remora.evidence.benchmark import DomainBenchmarkRunner
    cases_path = ROOT / "datasets" / "cyber_evidence_v1" / "cases" / "security_cases.jsonl"
    provider = CyberEvidenceProvider()
    runner = DomainBenchmarkRunner()
    raw_cases = runner.load_cases_from_jsonl(cases_path)
    from remora.evidence.benchmark import BenchmarkCase
    adapted = []
    for raw in raw_cases:
        data = raw.triage_kwargs if hasattr(raw, "triage_kwargs") and raw.triage_kwargs else _legacy_cyber_kwargs(raw)
        adapted.append(BenchmarkCase(
            case_id=raw.case_id,
            domain="cyber",
            title=raw.title,
            description=raw.description,
            triage_kwargs=data,
            expected_verdict=raw.expected_verdict,
            acceptable_verdicts=raw.acceptable_verdicts,
            must_not_verdict=raw.must_not_verdict,
            tags=raw.tags,
            reason=raw.reason,
        ))
    return runner.run(adapted, provider)


def _legacy_cyber_kwargs(case: "BenchmarkCase") -> dict:
    """Convert legacy security_cases.jsonl flat format to triage_kwargs."""
    import json as _json
    raw = _json.loads(json.dumps({
        "title": case.title,
        "description": case.description,
        "severity": case.triage_kwargs.get("severity", "medium"),
        "cve_ids": case.triage_kwargs.get("cve_ids", []),
        "cwe_ids": case.triage_kwargs.get("cwe_ids", []),
        "attack_ids": case.triage_kwargs.get("attack_ids", []),
        "packages": case.triage_kwargs.get("packages", []),
        "exposed": case.triage_kwargs.get("exposed", False),
        "production": case.triage_kwargs.get("production", False),
        "tool_signals": case.triage_kwargs.get("tool_signals", 1),
    }))
    return raw


def _load_cyber_cases():
    """Load legacy security_cases.jsonl format and convert to BenchmarkCase."""
    from remora.evidence.benchmark import BenchmarkCase
    import json as _json
    cases_path = ROOT / "datasets" / "cyber_evidence_v1" / "cases" / "security_cases.jsonl"
    cases = []
    with cases_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = _json.loads(line)
            triage_kwargs = {
                "title": row.get("title", ""),
                "description": row.get("description", ""),
                "severity": row.get("severity", "medium"),
                "cve_ids": row.get("cve_ids", []),
                "cwe_ids": row.get("cwe_ids", []),
                "attack_ids": row.get("attack_ids", []),
                "packages": row.get("packages", []),
                "exposed": row.get("exposed", False),
                "production": row.get("production", False),
                "tool_signals": row.get("tool_signals", 1),
            }
            must_not = None
            must_not_list = row.get("must_not", [])
            if must_not_list:
                must_not = must_not_list[0]
            cases.append(BenchmarkCase(
                case_id=row["case_id"],
                domain="cyber",
                title=row.get("title", ""),
                description=row.get("description", ""),
                triage_kwargs=triage_kwargs,
                expected_verdict=row["expected_verdict"],
                acceptable_verdicts=tuple(row.get("acceptable_verdicts", [])),
                must_not_verdict=must_not,
                tags=tuple(row.get("reason_tags", [])),
                reason=str(row.get("reason_tags", "")),
            ))
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="REMORA cross-domain governance benchmark")
    parser.add_argument(
        "--domain",
        choices=["cyber", "ai_governance", "finance", "all"],
        default="all",
        help="Domain to benchmark (default: all)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts" / "domain_benchmark_results.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-case details including actual verdict, confidence, and reasoning",
    )
    args = parser.parse_args()

    from remora.evidence.benchmark import DomainBenchmarkRunner, combine_results
    from remora.evidence.domains import AIGovernanceEvidenceProvider, FinanceEvidenceProvider

    runner = DomainBenchmarkRunner()
    domain_results = {}

    run_cyber = args.domain in {"cyber", "all"}
    run_aig = args.domain in {"ai_governance", "all"}
    run_fin = args.domain in {"finance", "all"}

    if run_cyber:
        print("Running cyber domain benchmark...")
        from remora.evidence.cyber import CyberEvidenceProvider
        cyber_cases = _load_cyber_cases()
        domain_results["cyber"] = runner.run(cyber_cases, CyberEvidenceProvider())

    if run_aig:
        print("Running ai_governance domain benchmark...")
        aig_cases_path = ROOT / "datasets" / "ai_governance_v1" / "cases" / "ai_governance_cases.jsonl"
        domain_results["ai_governance"] = runner.run_from_jsonl(aig_cases_path, AIGovernanceEvidenceProvider())

    if run_fin:
        print("Running finance domain benchmark...")
        fin_cases_path = ROOT / "datasets" / "finance_v1" / "cases" / "finance_cases.jsonl"
        domain_results["finance"] = runner.run_from_jsonl(fin_cases_path, FinanceEvidenceProvider())

    if args.verbose:
        print("\n--- Per-case detail ---")
        for domain, dr in domain_results.items():
            print(f"\n{domain.upper()}")
            for cr in dr.cases:
                status = "PASS" if cr.passed else ("CRIT" if cr.critical_fail else "FAIL")
                exp = cr.case.expected_verdict
                acc = ",".join(cr.case.acceptable_verdicts) if cr.case.acceptable_verdicts else "-"
                print(
                    f"  [{status}] {cr.case.case_id}\n"
                    f"         expected={exp} acceptable=[{acc}] must_not={cr.case.must_not_verdict}\n"
                    f"         actual={cr.actual_verdict} conf={cr.actual_confidence:.3f} "
                    f"class={cr.actual_risk_class}"
                )

    result = combine_results(domain_results)
    result.print_summary()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)
    print(f"\nResults written to {args.out}")

    if result.overall_critical_failure_rate > 0:
        print(f"\nERROR: {sum(r.critical_failures for r in result.domain_results.values())} critical failures detected.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
