# Author: Stian Skogbrott
# License: Apache-2.0
"""Cross-domain governance benchmark for REMORA evidence providers.

Benchmark cases are loaded from JSONL.  Each case specifies the exact kwargs
to pass to ``provider.triage()``, the expected verdict, verdicts that are
also acceptable (but not ideal), and a verdict that must never appear.

Metrics
-------
precision                overall pass rate (correct or acceptable / total)
escalation_recall        ESCALATE correct / total expected ESCALATE
fp_suppression_rate      FP correctly handled / total expected FP
report_ready_precision   REPORT_READY correct / total predicted REPORT_READY
critical_failure_rate    must-not verdict hit / total
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    """One benchmark case for a REMORA domain provider."""

    case_id: str
    domain: str
    title: str
    description: str
    triage_kwargs: dict[str, Any]
    expected_verdict: str
    acceptable_verdicts: tuple[str, ...]
    must_not_verdict: str | None
    tags: tuple[str, ...]
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkCase":
        return cls(
            case_id=str(data["case_id"]),
            domain=str(data["domain"]),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            triage_kwargs=dict(data["triage_kwargs"]),
            expected_verdict=str(data["expected_verdict"]),
            acceptable_verdicts=tuple(str(v) for v in data.get("acceptable_verdicts", [])),
            must_not_verdict=str(data["must_not_verdict"]) if data.get("must_not_verdict") else None,
            tags=tuple(str(t) for t in data.get("tags", [])),
            reason=str(data.get("reason", "")),
        )


@dataclass(frozen=True)
class BenchmarkCaseResult:
    """Result of running one benchmark case."""

    case: BenchmarkCase
    actual_verdict: str
    actual_confidence: float
    actual_risk_class: str
    passed: bool
    critical_fail: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "domain": self.case.domain,
            "expected_verdict": self.case.expected_verdict,
            "acceptable_verdicts": list(self.case.acceptable_verdicts),
            "actual_verdict": self.actual_verdict,
            "actual_confidence": round(self.actual_confidence, 3),
            "actual_risk_class": self.actual_risk_class,
            "passed": self.passed,
            "critical_fail": self.critical_fail,
            "tags": list(self.case.tags),
            "reason": self.case.reason,
        }


@dataclass
class DomainBenchmarkResult:
    """Aggregated benchmark result for one domain."""

    domain: str
    total: int
    passed: int
    critical_failures: int
    precision: float
    escalation_recall: float
    fp_suppression_rate: float
    report_ready_precision: float
    critical_failure_rate: float
    cases: list[BenchmarkCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "total": self.total,
            "passed": self.passed,
            "critical_failures": self.critical_failures,
            "precision": round(self.precision, 4),
            "escalation_recall": round(self.escalation_recall, 4),
            "fp_suppression_rate": round(self.fp_suppression_rate, 4),
            "report_ready_precision": round(self.report_ready_precision, 4),
            "critical_failure_rate": round(self.critical_failure_rate, 4),
            "cases": [c.to_dict() for c in self.cases],
        }


@dataclass
class AllDomainsBenchmarkResult:
    """Cross-domain benchmark result."""

    domain_results: dict[str, DomainBenchmarkResult]
    overall_precision: float
    overall_escalation_recall: float
    overall_fp_suppression_rate: float
    overall_critical_failure_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_precision": round(self.overall_precision, 4),
            "overall_escalation_recall": round(self.overall_escalation_recall, 4),
            "overall_fp_suppression_rate": round(self.overall_fp_suppression_rate, 4),
            "overall_critical_failure_rate": round(self.overall_critical_failure_rate, 4),
            "domains": {k: v.to_dict() for k, v in self.domain_results.items()},
        }

    def print_summary(self, file: Any = None) -> None:
        out = file or sys.stdout
        print("=" * 60, file=out)
        print("REMORA Cross-Domain Governance Benchmark", file=out)
        print("=" * 60, file=out)
        for domain, result in self.domain_results.items():
            print(f"\nDomain: {domain}", file=out)
            print(f"  Cases:              {result.total}", file=out)
            print(f"  Passed:             {result.passed}/{result.total}", file=out)
            print(f"  Precision:          {result.precision:.1%}", file=out)
            print(f"  Escalation recall:  {result.escalation_recall:.1%}", file=out)
            print(f"  FP suppression:     {result.fp_suppression_rate:.1%}", file=out)
            print(f"  Report-ready prec:  {result.report_ready_precision:.1%}", file=out)
            if result.critical_failures:
                print(f"  Critical failures:  {result.critical_failures} ⚠", file=out)
        print(f"\nOverall precision:          {self.overall_precision:.1%}", file=out)
        print(f"Overall escalation recall:  {self.overall_escalation_recall:.1%}", file=out)
        print(f"Overall FP suppression:     {self.overall_fp_suppression_rate:.1%}", file=out)
        print("=" * 60, file=out)


def _safe_verdict(result: Any) -> str:
    v = getattr(result, "verdict", None)
    if v is None:
        return "UNKNOWN"
    return v.value if hasattr(v, "value") else str(v)


def _safe_confidence(result: Any) -> float:
    return float(getattr(result, "confidence", 0.0))


def _safe_risk_class(result: Any) -> str:
    for attr in ("exploit_classification", "risk_classification", "finance_risk_classification"):
        v = getattr(result, attr, None)
        if v is not None:
            return v.value if hasattr(v, "value") else str(v)
    return "UNKNOWN"


class DomainBenchmarkRunner:
    """Runs benchmark cases against a domain evidence provider."""

    def load_cases_from_jsonl(self, path: Path | str) -> list[BenchmarkCase]:
        p = Path(path)
        cases = []
        with p.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    cases.append(BenchmarkCase.from_dict(json.loads(line)))
                except Exception as exc:
                    raise ValueError(f"{p.name} line {line_no}: {exc}") from exc
        return cases

    def run(self, cases: list[BenchmarkCase], provider: Any) -> DomainBenchmarkResult:
        if not cases:
            raise ValueError("No cases provided.")
        domain = cases[0].domain
        case_results: list[BenchmarkCaseResult] = []

        for case in cases:
            try:
                triage_result = provider.triage(**case.triage_kwargs)
            except Exception as exc:
                raise RuntimeError(f"triage() failed for case {case.case_id!r}: {exc}") from exc

            actual_verdict = _safe_verdict(triage_result)
            actual_confidence = _safe_confidence(triage_result)
            actual_risk_class = _safe_risk_class(triage_result)

            correct = (
                actual_verdict == case.expected_verdict
                or actual_verdict in case.acceptable_verdicts
            )
            critical = case.must_not_verdict is not None and actual_verdict == case.must_not_verdict
            passed = correct and not critical

            case_results.append(BenchmarkCaseResult(
                case=case,
                actual_verdict=actual_verdict,
                actual_confidence=actual_confidence,
                actual_risk_class=actual_risk_class,
                passed=passed,
                critical_fail=critical,
            ))

        return _aggregate(domain, case_results)

    def run_from_jsonl(self, path: Path | str, provider: Any) -> DomainBenchmarkResult:
        cases = self.load_cases_from_jsonl(path)
        return self.run(cases, provider)


def _aggregate(domain: str, case_results: list[BenchmarkCaseResult]) -> DomainBenchmarkResult:
    total = len(case_results)
    passed = sum(1 for r in case_results if r.passed)
    critical = sum(1 for r in case_results if r.critical_fail)
    precision = passed / total if total else 0.0

    escalate_expected = [r for r in case_results if r.case.expected_verdict == "ESCALATE"]
    escalate_correct = sum(1 for r in escalate_expected if r.actual_verdict == "ESCALATE")
    escalation_recall = escalate_correct / len(escalate_expected) if escalate_expected else 1.0

    fp_expected = [r for r in case_results if r.case.expected_verdict == "LIKELY_FALSE_POSITIVE"]
    fp_suppressed = sum(
        1 for r in fp_expected
        if r.actual_verdict in {"LIKELY_FALSE_POSITIVE", "NEEDS_REVIEW"}
        and r.actual_verdict != "ESCALATE"
        and r.actual_verdict != "REPORT_READY"
    )
    fp_suppression = fp_suppressed / len(fp_expected) if fp_expected else 1.0

    rr_predicted = [r for r in case_results if r.actual_verdict == "REPORT_READY"]
    rr_correct = sum(
        1 for r in rr_predicted
        if r.case.expected_verdict == "REPORT_READY"
        or "REPORT_READY" in r.case.acceptable_verdicts
    )
    rr_precision = rr_correct / len(rr_predicted) if rr_predicted else 1.0

    return DomainBenchmarkResult(
        domain=domain,
        total=total,
        passed=passed,
        critical_failures=critical,
        precision=precision,
        escalation_recall=escalation_recall,
        fp_suppression_rate=fp_suppression,
        report_ready_precision=rr_precision,
        critical_failure_rate=critical / total if total else 0.0,
        cases=case_results,
    )


def combine_results(domain_results: dict[str, DomainBenchmarkResult]) -> AllDomainsBenchmarkResult:
    """Combine results from multiple domains into a single summary."""
    if not domain_results:
        return AllDomainsBenchmarkResult(
            domain_results={},
            overall_precision=0.0,
            overall_escalation_recall=0.0,
            overall_fp_suppression_rate=0.0,
            overall_critical_failure_rate=0.0,
        )

    results = list(domain_results.values())
    total = sum(r.total for r in results)
    passed = sum(r.passed for r in results)
    critical = sum(r.critical_failures for r in results)

    escalate_denom = sum(
        sum(1 for c in r.cases if c.case.expected_verdict == "ESCALATE") for r in results
    )
    escalate_num = sum(
        sum(1 for c in r.cases if c.case.expected_verdict == "ESCALATE" and c.actual_verdict == "ESCALATE")
        for r in results
    )
    fp_denom = sum(
        sum(1 for c in r.cases if c.case.expected_verdict == "LIKELY_FALSE_POSITIVE") for r in results
    )
    fp_num = sum(
        sum(
            1 for c in r.cases
            if c.case.expected_verdict == "LIKELY_FALSE_POSITIVE"
            and c.actual_verdict in {"LIKELY_FALSE_POSITIVE", "NEEDS_REVIEW"}
            and c.actual_verdict not in {"ESCALATE", "REPORT_READY"}
        )
        for r in results
    )

    return AllDomainsBenchmarkResult(
        domain_results=domain_results,
        overall_precision=passed / total if total else 0.0,
        overall_escalation_recall=escalate_num / escalate_denom if escalate_denom else 1.0,
        overall_fp_suppression_rate=fp_num / fp_denom if fp_denom else 1.0,
        overall_critical_failure_rate=critical / total if total else 0.0,
    )


__all__ = [
    "AllDomainsBenchmarkResult",
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "DomainBenchmarkResult",
    "DomainBenchmarkRunner",
    "combine_results",
]
