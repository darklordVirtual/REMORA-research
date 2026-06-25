#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA live benchmark — oracle consensus vs. static evidence.

Runs every benchmark case through the live GO-STAR REMORA Cloudflare Worker
(3 AI oracle models: llama-3.1-8b, llama-3.3-70b, mistral-7b) and compares
results with the static evidence provider verdicts.

Metrics
-------
oracle_directional_precision
    Fraction of ESCALATE/REPORT_READY/LIKELY_FP cases where the oracle
    correctly identifies the risk direction (YES for risk cases, NO for FP).

oracle_escalation_identification
    For ESCALATE-expected cases: fraction where oracle says YES (true).

oracle_fp_identification
    For LIKELY_FALSE_POSITIVE-expected cases: fraction where oracle says NO.

oracle_static_agreement
    Fraction of cases where oracle direction matches static evidence verdict
    direction (both identify the same risk level).

fusion_needs_review_rate
    Fraction where oracle and static disagree — these should always route
    to NEEDS_REVIEW (human escalation) in the full pipeline.

Usage
-----
    python scripts/run_live_benchmark.py
    python scripts/run_live_benchmark.py --domain cyber
    python scripts/run_live_benchmark.py --verbose
    python scripts/run_live_benchmark.py --out artifacts/live_benchmark_results.json

Requires network access to go-star-remora.razorsharp.workers.dev.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from remora.evidence.benchmark import BenchmarkCase


# ---------------------------------------------------------------------------
# Question formulation
# ---------------------------------------------------------------------------

def _cyber_question(title: str, description: str, kwargs: dict) -> tuple[str, str, str]:
    """Return (question, context, use_case) for a cyber finding."""
    cves = kwargs.get("cve_ids", [])
    cwes = kwargs.get("cwe_ids", [])
    exposed = kwargs.get("exposed", False)
    production = kwargs.get("production", False)
    env_ctx = "production" if production else "development/test"
    exposure = "internet-facing" if exposed else "internal"
    ids = ", ".join(cves + cwes) if (cves or cwes) else "no specific CVE/CWE"

    question = (
        f"Is this a real, exploitable security vulnerability in a {env_ctx} "
        f"{exposure} environment? {title}. {description}. Identifiers: {ids}."
    )
    context = (
        f"Severity: {kwargs.get('severity','unknown')}. "
        f"Production: {production}. Exposed: {exposed}. "
        f"Tool signals: {kwargs.get('tool_signals',1)}."
    )
    return question, context, "exploitability"


def _fp_cyber_question(title: str, description: str, kwargs: dict) -> tuple[str, str, str]:
    """Return (question, context, use_case) for a cyber FP case."""
    question = (
        f"Is this security scanner finding a false positive, benign artifact, "
        f"or non-exploitable placeholder? {title}. {description}."
    )
    context = (
        f"Severity: {kwargs.get('severity','low')}. "
        f"Production: {kwargs.get('production',False)}. "
        f"Tool signals: {kwargs.get('tool_signals',1)}."
    )
    return question, context, "fp_check"


def _ai_gov_question(title: str, description: str, kwargs: dict) -> tuple[str, str, str]:
    in_prod = kwargs.get("in_production", False)
    exposed = kwargs.get("exposed_endpoint", False)
    question = (
        f"Does this AI deployment scenario represent a genuine AI governance risk "
        f"or policy violation? {title}. {description}."
    )
    context = (
        f"Production deployment: {in_prod}. Exposed endpoint: {exposed}. "
        f"Severity: {kwargs.get('severity','unknown')}. "
        f"Tool signals: {kwargs.get('tool_signals',1)}."
    )
    return question, context, "ai_security"


def _finance_question(title: str, description: str, kwargs: dict) -> tuple[str, str, str]:
    sdn = kwargs.get("sdnmatch", False)
    pep = kwargs.get("pep_exposure", False)
    hi_risk = kwargs.get("high_risk_jurisdiction", False)
    question = (
        f"Does this transaction or customer scenario represent a genuine AML, "
        f"sanctions, or financial compliance risk requiring action? "
        f"{title}. {description}."
    )
    context = (
        f"OFAC SDN match: {sdn}. PEP exposure: {pep}. "
        f"High-risk jurisdiction: {hi_risk}. "
        f"Severity: {kwargs.get('severity','unknown')}. "
        f"Tool signals: {kwargs.get('tool_signals',1)}."
    )
    return question, context, "aml_compliance"


def formulate_question(case: "BenchmarkCase") -> tuple[str, str, str, str]:
    """Return (question, context, use_case, endpoint) for a benchmark case."""
    domain = case.domain
    title = case.title
    desc = case.description
    kwargs = case.triage_kwargs
    ev = case.expected_verdict

    if domain == "cyber":
        if ev == "LIKELY_FALSE_POSITIVE" or "false_positive" in case.tags or "test_fixture" in case.tags:
            q, ctx, uc = _fp_cyber_question(title, desc, kwargs)
            return q, ctx, uc, "/false-positive"
        else:
            q, ctx, uc = _cyber_question(title, desc, kwargs)
            return q, ctx, uc, "/assess"
    elif domain == "ai_governance":
        q, ctx, uc = _ai_gov_question(title, desc, kwargs)
        return q, ctx, uc, "/assess"
    else:
        q, ctx, uc = _finance_question(title, desc, kwargs)
        return q, ctx, uc, "/assess"


# ---------------------------------------------------------------------------
# Oracle verdict → directional signal
# ---------------------------------------------------------------------------

def oracle_direction(verdict: bool | None, confidence: float, endpoint: str) -> str:
    """
    Map oracle response to a directional signal:
      'risk'   — oracle says YES, this is a real risk / not a FP
      'benign' — oracle says NO, this is benign / is a FP
      'unsure' — oracle is uncertain
    """
    if verdict is None or confidence < 0.45:
        return "unsure"
    if endpoint == "/false-positive":
        # true = IS a false positive → benign; false = NOT a FP → risk
        return "benign" if verdict is True else "risk"
    else:
        # true = IS a risk; false = NOT a risk → benign
        return "risk" if verdict is True else "benign"


def expected_direction(expected_verdict: str) -> str:
    if expected_verdict in {"ESCALATE", "REPORT_READY"}:
        return "risk"
    if expected_verdict == "LIKELY_FALSE_POSITIVE":
        return "benign"
    return "neutral"  # NEEDS_REVIEW is not directional


def static_direction(static_verdict: str) -> str:
    if static_verdict in {"ESCALATE", "REPORT_READY"}:
        return "risk"
    if static_verdict == "LIKELY_FALSE_POSITIVE":
        return "benign"
    return "neutral"


# ---------------------------------------------------------------------------
# Live case result
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field as dc_field
from typing import Any

@dataclass
class LiveCaseResult:
    case_id: str
    domain: str
    expected_verdict: str
    static_verdict: str
    static_confidence: float
    oracle_direction_val: str
    oracle_verdict: bool | None
    oracle_confidence: float
    oracle_iterations: int
    oracle_calls: int
    oracle_summary: str
    oracle_claim: str
    latency_ms: int
    endpoint: str
    question: str
    direction_correct: bool      # oracle direction matches expected
    oracle_static_agree: bool    # oracle direction matches static direction
    is_directional: bool         # case has a clear expected direction (not NEEDS_REVIEW)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "domain": self.domain,
            "expected_verdict": self.expected_verdict,
            "static_verdict": self.static_verdict,
            "static_confidence": round(self.static_confidence, 3),
            "oracle_direction": self.oracle_direction_val,
            "oracle_verdict": self.oracle_verdict,
            "oracle_confidence": round(self.oracle_confidence, 3),
            "oracle_iterations": self.oracle_iterations,
            "oracle_calls": self.oracle_calls,
            "oracle_summary": self.oracle_summary,
            "oracle_claim": self.oracle_claim,
            "latency_ms": self.latency_ms,
            "endpoint": self.endpoint,
            "question": self.question,
            "direction_correct": self.direction_correct,
            "oracle_static_agree": self.oracle_static_agree,
        }


@dataclass
class LiveBenchmarkResult:
    domain: str
    total: int
    directional_cases: int
    oracle_directional_precision: float
    oracle_escalation_identification: float
    oracle_fp_identification: float
    oracle_static_agreement: float
    mean_confidence: float
    mean_latency_ms: float
    total_oracle_calls: int
    cases: list[LiveCaseResult] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "total": self.total,
            "directional_cases": self.directional_cases,
            "oracle_directional_precision": round(self.oracle_directional_precision, 4),
            "oracle_escalation_identification": round(self.oracle_escalation_identification, 4),
            "oracle_fp_identification": round(self.oracle_fp_identification, 4),
            "oracle_static_agreement": round(self.oracle_static_agreement, 4),
            "mean_confidence": round(self.mean_confidence, 4),
            "mean_latency_ms": round(self.mean_latency_ms, 1),
            "total_oracle_calls": self.total_oracle_calls,
            "cases": [c.to_dict() for c in self.cases],
        }


@dataclass
class AllLiveResults:
    domain_results: dict[str, LiveBenchmarkResult]
    overall_oracle_directional_precision: float
    overall_oracle_static_agreement: float
    overall_fusion_needs_review_rate: float
    total_oracle_calls: int
    total_latency_ms: int
    worker_status: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_oracle_directional_precision": round(self.overall_oracle_directional_precision, 4),
            "overall_oracle_static_agreement": round(self.overall_oracle_static_agreement, 4),
            "overall_fusion_needs_review_rate": round(self.overall_fusion_needs_review_rate, 4),
            "total_oracle_calls": self.total_oracle_calls,
            "total_latency_ms": self.total_latency_ms,
            "worker_status": self.worker_status,
            "domains": {k: v.to_dict() for k, v in self.domain_results.items()},
        }

    def print_summary(self, file: Any = None) -> None:
        out = file or sys.stdout
        w = self.worker_status
        print("=" * 68, file=out)
        print("REMORA Live Oracle Benchmark", file=out)
        print(f"Worker: go-star-remora  Oracles: {w.get('n_oracles',0)}  "
              f"({', '.join(k for k,v in w.get('oracles',{}).items() if v)})", file=out)
        print(f"Models: {w.get('models',{}).get('groq_fast','?')} / "
              f"{w.get('models',{}).get('groq_strong','?')} / "
              f"{w.get('models',{}).get('openrouter','?')}", file=out)
        print("=" * 68, file=out)
        for domain, dr in self.domain_results.items():
            print(f"\nDomain: {domain}", file=out)
            print(f"  Cases:                          {dr.total}", file=out)
            print(f"  Oracle directional precision:   {dr.oracle_directional_precision:.1%}", file=out)
            print(f"  Escalation identification:      {dr.oracle_escalation_identification:.1%}", file=out)
            print(f"  FP identification:              {dr.oracle_fp_identification:.1%}", file=out)
            print(f"  Oracle-static agreement:        {dr.oracle_static_agreement:.1%}", file=out)
            print(f"  Mean oracle confidence:         {dr.mean_confidence:.2f}", file=out)
            print(f"  Mean latency:                   {dr.mean_latency_ms:.0f} ms", file=out)
            print(f"  Total oracle calls:             {dr.total_oracle_calls}", file=out)
        print(f"\nOverall directional precision:  {self.overall_oracle_directional_precision:.1%}", file=out)
        print(f"Overall oracle-static agreement:{self.overall_oracle_static_agreement:.1%}", file=out)
        print(f"Disagreement -> NEEDS_REVIEW:    {self.overall_fusion_needs_review_rate:.1%}", file=out)
        print(f"Total oracle API calls:         {self.total_oracle_calls}", file=out)
        print(f"Total latency:                  {self.total_latency_ms / 1000:.1f} s", file=out)
        print("=" * 68, file=out)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _load_cyber_cases():
    from remora.evidence.benchmark import BenchmarkCase
    cases_path = ROOT / "datasets" / "cyber_evidence_v1" / "cases" / "security_cases.jsonl"
    cases = []
    with cases_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = json.loads(line)
            triage_kwargs = {k: row[k] for k in (
                "title", "description", "severity", "cve_ids", "cwe_ids",
                "attack_ids", "packages", "exposed", "production", "tool_signals"
            ) if k in row}
            must_not = row.get("must_not", [])
            cases.append(BenchmarkCase(
                case_id=row["case_id"], domain="cyber",
                title=row.get("title", ""), description=row.get("description", ""),
                triage_kwargs=triage_kwargs,
                expected_verdict=row["expected_verdict"],
                acceptable_verdicts=tuple(row.get("acceptable_verdicts", [])),
                must_not_verdict=must_not[0] if must_not else None,
                tags=tuple(row.get("reason_tags", [])),
            ))
    return cases


def run_domain(domain: str, cases: list, verbose: bool = False) -> LiveBenchmarkResult:
    from remora.evidence.worker_client import REMORAWorkerClient
    from remora.evidence.domains import get_provider
    from remora.evidence.cyber import CyberEvidenceProvider

    client = REMORAWorkerClient()
    provider = CyberEvidenceProvider() if domain == "cyber" else get_provider(domain)

    case_results: list[LiveCaseResult] = []

    for case in cases:
        # 1. Static evidence verdict
        try:
            static_r = provider.triage(**case.triage_kwargs)
            sv = static_r.verdict.value if hasattr(static_r.verdict, "value") else str(static_r.verdict)
            sc = float(static_r.confidence)
        except Exception as exc:
            sv, sc = "ERROR", 0.0
            print(f"  Static error on {case.case_id}: {exc}", file=sys.stderr)

        # 2. Oracle question
        question, context, use_case, endpoint = formulate_question(case)

        # 3. Oracle call (with retry on rate-limit / zero-confidence response)
        oc = None
        for attempt in range(3):
            try:
                if endpoint == "/false-positive":
                    oc = client.fp_check(
                        description=f"{case.title}. {case.description}",
                        cwe=case.triage_kwargs.get("cwe_ids", [""])[0] if case.triage_kwargs.get("cwe_ids") else "",
                        context=context,
                    )
                else:
                    oc = client.assess(question=question, context=context, use_case=use_case)
            except Exception as exc:
                print(f"  Oracle error on {case.case_id} (attempt {attempt+1}): {exc}", file=sys.stderr)
                time.sleep(3 + attempt * 2)
                continue
            # Retry if confidence=0 and not clearly degraded (likely rate-limit burst)
            if oc is not None and oc.confidence == 0.0 and oc.oracle_calls == 0 and not oc.degraded:
                time.sleep(3 + attempt * 2)
                oc = None
                continue
            break
        # Respect rate-limit between cases
        time.sleep(2)

        if oc is None:
            od, ov, oconf, oiter, ocalls, osum, oclaim, latms = "unsure", None, 0.0, 0, 0, "ERROR", "", 0
        else:
            od = oracle_direction(oc.verdict, oc.confidence, endpoint)
            ov, oconf, oiter = oc.verdict, oc.confidence, oc.iterations
            ocalls, osum, oclaim, latms = oc.oracle_calls, oc.summary, oc.claim, oc.latency_ms

        exp_dir = expected_direction(case.expected_verdict)
        stat_dir = static_direction(sv)
        dir_correct = (exp_dir != "neutral") and (od == exp_dir)
        agree = (od != "unsure") and (od == stat_dir) or (od == "unsure" and stat_dir == "neutral")

        lr = LiveCaseResult(
            case_id=case.case_id, domain=domain,
            expected_verdict=case.expected_verdict, static_verdict=sv,
            static_confidence=sc, oracle_direction_val=od,
            oracle_verdict=ov, oracle_confidence=oconf,
            oracle_iterations=oiter, oracle_calls=ocalls,
            oracle_summary=osum, oracle_claim=oclaim,
            latency_ms=latms, endpoint=endpoint, question=question,
            direction_correct=dir_correct,
            oracle_static_agree=agree,
            is_directional=(exp_dir != "neutral"),
        )
        case_results.append(lr)

        if verbose:
            status = "OK" if dir_correct else "FAIL" if exp_dir != "neutral" else "~"
            vstr = "YES" if ov is True else "NO" if ov is False else "UNC"
            print(f"  [{status}] {case.case_id}\n"
                  f"       expected={case.expected_verdict} static={sv} "
                  f"oracle={od.upper()}({vstr}) conf={oconf:.2f} {osum}")

    return _aggregate_live(domain, case_results)


def _aggregate_live(domain: str, results: list[LiveCaseResult]) -> LiveBenchmarkResult:
    directional = [r for r in results if r.is_directional]
    dir_correct = [r for r in directional if r.direction_correct]
    esc_cases = [r for r in results if r.expected_verdict == "ESCALATE" and r.is_directional]
    esc_correct = [r for r in esc_cases if r.oracle_direction_val == "risk"]
    fp_cases = [r for r in results if r.expected_verdict == "LIKELY_FALSE_POSITIVE" and r.is_directional]
    fp_correct = [r for r in fp_cases if r.oracle_direction_val == "benign"]
    agree = [r for r in results if r.oracle_static_agree]
    confs = [r.oracle_confidence for r in results if r.oracle_confidence > 0]
    lats = [r.latency_ms for r in results if r.latency_ms > 0]

    return LiveBenchmarkResult(
        domain=domain,
        total=len(results),
        directional_cases=len(directional),
        oracle_directional_precision=len(dir_correct) / len(directional) if directional else 0.0,
        oracle_escalation_identification=len(esc_correct) / len(esc_cases) if esc_cases else 1.0,
        oracle_fp_identification=len(fp_correct) / len(fp_cases) if fp_cases else 1.0,
        oracle_static_agreement=len(agree) / len(results) if results else 0.0,
        mean_confidence=sum(confs) / len(confs) if confs else 0.0,
        mean_latency_ms=sum(lats) / len(lats) if lats else 0.0,
        total_oracle_calls=sum(r.oracle_calls for r in results),
        cases=results,
    )


def _combine_live(domain_results: dict[str, LiveBenchmarkResult], wstatus: dict) -> AllLiveResults:
    all_cases = [c for r in domain_results.values() for c in r.cases]
    directional = [c for c in all_cases if c.is_directional]
    dir_correct = [c for c in directional if c.direction_correct]
    agree = [c for c in all_cases if c.oracle_static_agree]
    disagree_dir = [c for c in all_cases if not c.oracle_static_agree and c.oracle_direction_val != "unsure"]

    return AllLiveResults(
        domain_results=domain_results,
        overall_oracle_directional_precision=len(dir_correct)/len(directional) if directional else 0.0,
        overall_oracle_static_agreement=len(agree)/len(all_cases) if all_cases else 0.0,
        overall_fusion_needs_review_rate=len(disagree_dir)/len(all_cases) if all_cases else 0.0,
        total_oracle_calls=sum(r.total_oracle_calls for r in domain_results.values()),
        total_latency_ms=sum(c.latency_ms for c in all_cases),
        worker_status=wstatus,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="REMORA live oracle benchmark")
    parser.add_argument("--domain", choices=["cyber","ai_governance","finance","all"], default="all")
    parser.add_argument("--out", type=Path, default=ROOT/"artifacts"/"live_benchmark_results.json")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    from remora.evidence.worker_client import REMORAWorkerClient
    from remora.evidence.benchmark import DomainBenchmarkRunner

    client = REMORAWorkerClient()
    print("Checking worker status...")
    try:
        wstatus = client.status()
        n = wstatus.get("n_oracles", 0)
        print(f"  Worker: {wstatus.get('worker')}  Oracles: {n}/3  "
              f"Ready: {wstatus.get('ready')}")
    except Exception as exc:
        print(f"  Worker unavailable: {exc}", file=sys.stderr)
        sys.exit(2)

    runner = DomainBenchmarkRunner()
    domain_results: dict[str, LiveBenchmarkResult] = {}

    if args.domain in {"cyber", "all"}:
        print("\nRunning cyber domain (live oracle)...")
        cases = _load_cyber_cases()
        domain_results["cyber"] = run_domain("cyber", cases, verbose=args.verbose)

    if args.domain in {"ai_governance", "all"}:
        print("\nRunning ai_governance domain (live oracle)...")
        cases = runner.load_cases_from_jsonl(ROOT/"datasets"/"ai_governance_v1"/"cases"/"ai_governance_cases.jsonl")
        domain_results["ai_governance"] = run_domain("ai_governance", cases, verbose=args.verbose)

    if args.domain in {"finance", "all"}:
        print("\nRunning finance domain (live oracle)...")
        cases = runner.load_cases_from_jsonl(ROOT/"datasets"/"finance_v1"/"cases"/"finance_cases.jsonl")
        domain_results["finance"] = run_domain("finance", cases, verbose=args.verbose)

    result = _combine_live(domain_results, wstatus)
    result.print_summary()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)
    print(f"\nResults written to {args.out}")


if __name__ == "__main__":
    main()
