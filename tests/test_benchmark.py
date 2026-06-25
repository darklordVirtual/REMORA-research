from __future__ import annotations

from pathlib import Path

from remora.evidence.benchmark import (
    BenchmarkCase,
    DomainBenchmarkResult,
    DomainBenchmarkRunner,
    combine_results,
)


def _make_case(
    case_id: str,
    domain: str,
    expected: str,
    acceptable: tuple[str, ...] = (),
    must_not: str | None = None,
    triage_kwargs: dict | None = None,
) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=case_id,
        domain=domain,
        title=f"Test {case_id}",
        description="test",
        triage_kwargs=triage_kwargs or {
            "title": f"Test {case_id}",
            "description": "test",
            "severity": "high",
        },
        expected_verdict=expected,
        acceptable_verdicts=acceptable,
        must_not_verdict=must_not,
        tags=(),
    )


class _MockProvider:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    def triage(self, *, title: str, **_: object) -> "_MockResult":
        verdict = self._responses.get(title, "NEEDS_REVIEW")
        return _MockResult(verdict)


class _MockResult:
    def __init__(self, verdict: str) -> None:
        self._verdict = verdict
        self.confidence = 0.75

    @property
    def verdict(self) -> "_MockVerdict":
        return _MockVerdict(self._verdict)

    @property
    def exploit_classification(self) -> "_MockVerdict":
        return _MockVerdict("EMERGING_OR_UNKNOWN")


class _MockVerdict:
    def __init__(self, value: str) -> None:
        self.value = value


def test_benchmark_runner_all_pass() -> None:
    cases = [
        _make_case("c1", "cyber", "ESCALATE", triage_kwargs={"title": "c1", "description": "x", "severity": "high"}),
        _make_case("c2", "cyber", "REPORT_READY", triage_kwargs={"title": "c2", "description": "x", "severity": "high"}),
        _make_case("c3", "cyber", "NEEDS_REVIEW", triage_kwargs={"title": "c3", "description": "x", "severity": "medium"}),
    ]
    provider = _MockProvider({"c1": "ESCALATE", "c2": "REPORT_READY", "c3": "NEEDS_REVIEW"})
    runner = DomainBenchmarkRunner()
    result = runner.run(cases, provider)
    assert result.total == 3
    assert result.passed == 3
    assert result.precision == 1.0
    assert result.critical_failures == 0


def test_benchmark_runner_acceptable_verdict_passes() -> None:
    cases = [
        _make_case("c1", "cyber", "REPORT_READY", acceptable=("NEEDS_REVIEW",),
                   triage_kwargs={"title": "c1", "description": "x", "severity": "high"}),
    ]
    provider = _MockProvider({"c1": "NEEDS_REVIEW"})
    runner = DomainBenchmarkRunner()
    result = runner.run(cases, provider)
    assert result.passed == 1


def test_benchmark_runner_must_not_fails() -> None:
    cases = [
        _make_case("c1", "cyber", "ESCALATE", must_not="LIKELY_FALSE_POSITIVE",
                   triage_kwargs={"title": "c1", "description": "x", "severity": "critical"}),
    ]
    provider = _MockProvider({"c1": "LIKELY_FALSE_POSITIVE"})
    runner = DomainBenchmarkRunner()
    result = runner.run(cases, provider)
    assert result.passed == 0
    assert result.critical_failures == 1
    assert result.critical_failure_rate == 1.0


def test_escalation_recall_calculation() -> None:
    cases = [
        _make_case("c1", "cyber", "ESCALATE", triage_kwargs={"title": "c1", "description": "x", "severity": "critical"}),
        _make_case("c2", "cyber", "ESCALATE", triage_kwargs={"title": "c2", "description": "x", "severity": "critical"}),
        _make_case("c3", "cyber", "REPORT_READY", triage_kwargs={"title": "c3", "description": "x", "severity": "high"}),
    ]
    # c1 escalated correctly, c2 gets NEEDS_REVIEW, c3 gets REPORT_READY
    provider = _MockProvider({"c1": "ESCALATE", "c2": "NEEDS_REVIEW", "c3": "REPORT_READY"})
    runner = DomainBenchmarkRunner()
    result = runner.run(cases, provider)
    assert result.escalation_recall == 0.5  # 1/2 escalations correct


def test_fp_suppression_rate() -> None:
    cases = [
        _make_case("fp1", "cyber", "LIKELY_FALSE_POSITIVE",
                   triage_kwargs={"title": "fp1", "description": "x", "severity": "low"}),
        _make_case("fp2", "cyber", "LIKELY_FALSE_POSITIVE",
                   triage_kwargs={"title": "fp2", "description": "x", "severity": "low"}),
    ]
    # fp1 correctly suppressed as NEEDS_REVIEW, fp2 incorrectly escalated
    provider = _MockProvider({"fp1": "NEEDS_REVIEW", "fp2": "ESCALATE"})
    runner = DomainBenchmarkRunner()
    result = runner.run(cases, provider)
    assert result.fp_suppression_rate == 0.5  # 1/2 FP cases handled correctly


def test_combine_results_aggregates_correctly() -> None:
    r1 = DomainBenchmarkResult(
        domain="cyber", total=10, passed=9, critical_failures=0,
        precision=0.9, escalation_recall=1.0, fp_suppression_rate=1.0,
        report_ready_precision=0.9, critical_failure_rate=0.0,
    )
    r2 = DomainBenchmarkResult(
        domain="finance", total=10, passed=8, critical_failures=1,
        precision=0.8, escalation_recall=0.75, fp_suppression_rate=1.0,
        report_ready_precision=0.85, critical_failure_rate=0.1,
    )
    combined = combine_results({"cyber": r1, "finance": r2})
    assert combined.overall_precision == 0.85
    assert combined.overall_critical_failure_rate == 0.05


def test_benchmark_runner_loads_from_jsonl() -> None:
    runner = DomainBenchmarkRunner()
    cases_path = Path(__file__).resolve().parents[1] / "datasets" / "finance_v1" / "cases" / "finance_cases.jsonl"
    cases = runner.load_cases_from_jsonl(cases_path)
    assert len(cases) >= 5
    for c in cases:
        assert c.domain == "finance"
        assert c.triage_kwargs


def test_full_cyber_benchmark_no_critical_failures() -> None:
    """Smoke test: run the full cyber benchmark and verify zero critical failures."""
    import json as _json
    from remora.evidence.cyber import CyberEvidenceProvider
    runner = DomainBenchmarkRunner()
    cases_path = Path(__file__).resolve().parents[1] / "datasets" / "cyber_evidence_v1" / "cases" / "security_cases.jsonl"
    raw_cases = []
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
            must_not_list = row.get("must_not", [])
            raw_cases.append(BenchmarkCase(
                case_id=row["case_id"],
                domain="cyber",
                title=row.get("title", ""),
                description=row.get("description", ""),
                triage_kwargs=triage_kwargs,
                expected_verdict=row["expected_verdict"],
                acceptable_verdicts=tuple(row.get("acceptable_verdicts", [])),
                must_not_verdict=must_not_list[0] if must_not_list else None,
                tags=tuple(row.get("reason_tags", [])),
            ))
    result = runner.run(raw_cases, CyberEvidenceProvider())
    assert result.critical_failures == 0, (
        f"Critical failures: {[c.case.case_id for c in result.cases if c.critical_fail]}"
    )


def test_full_ai_governance_benchmark_no_critical_failures() -> None:
    from remora.evidence.domains.ai_governance import AIGovernanceEvidenceProvider
    runner = DomainBenchmarkRunner()
    cases_path = Path(__file__).resolve().parents[1] / "datasets" / "ai_governance_v1" / "cases" / "ai_governance_cases.jsonl"
    result = runner.run_from_jsonl(cases_path, AIGovernanceEvidenceProvider())
    assert result.critical_failures == 0, (
        f"Critical failures: {[c.case.case_id for c in result.cases if c.critical_fail]}"
    )


def test_full_finance_benchmark_no_critical_failures() -> None:
    from remora.evidence.domains.finance import FinanceEvidenceProvider
    runner = DomainBenchmarkRunner()
    cases_path = Path(__file__).resolve().parents[1] / "datasets" / "finance_v1" / "cases" / "finance_cases.jsonl"
    result = runner.run_from_jsonl(cases_path, FinanceEvidenceProvider())
    assert result.critical_failures == 0, (
        f"Critical failures: {[c.case.case_id for c in result.cases if c.critical_fail]}"
    )
